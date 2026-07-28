"""Tests for the agent spec and the factory that instantiates it.

The spec is the platform's most load-bearing type - the Builder writes it, the
database versions it, and clients commit it to their own repositories - so what
is guarded here is its contract: it round-trips, it refuses contradictions, and
it never carries a secret.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.agents.capabilities import load_builtins
from app.agents.capabilities.budget import SpendLimit
from app.agents.factory import DEFAULT_MAX_STEPS, build_agent
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.core.secret_kinds import ApiKeySecret


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


def _model_spec(params: dict | None = None) -> ModelRequestSpec:
    return ModelRequestSpec(
        profile_id=uuid.uuid4(),
        label="GPT-4.1 (prod)",
        provider="openai",
        model="gpt-4.1",
        params=params or {},
        credential=ResolvedCredential(
            provider="openai", secret=ApiKeySecret(api_key="sk-test-key")
        ),
        fallbacks=[],
    )


class TestSpecContract:
    def test_yaml_round_trips(self):
        spec = AgentSpec(
            name="Support Copilot",
            description="Answers from the product wiki.",
            instructions="Cite your sources.",
            capabilities=[{"id": "knowledge", "config": {"default_top_k": 8}}],
        )
        assert AgentSpec.from_yaml(spec.to_yaml()) == spec

    def test_a_tool_cannot_be_bound_twice(self):
        """A duplicate would silently shadow itself in the toolset."""
        with pytest.raises(ValueError, match="more than once"):
            AgentSpec(name="x", capabilities=[{"id": "a"}, {"id": "a"}])

    def test_unknown_fields_are_rejected(self):
        """A typo in a hand-written spec must fail, not be silently dropped."""
        with pytest.raises(ValueError):
            AgentSpec.from_yaml("name: x\ninstrucitons: typo\n")

    def test_yaml_must_be_a_mapping(self):
        with pytest.raises(ValueError, match="mapping"):
            AgentSpec.from_yaml("- just\n- a list\n")

    def test_spec_carries_references_not_values(self):
        """What makes a spec safe to commit to a client's git repository."""
        spec = AgentSpec(name="x", model_profile_id=uuid.uuid4())
        rendered = spec.to_yaml()
        assert "api_key" not in rendered
        assert "sk-" not in rendered

    def test_negative_budgets_are_refused(self):
        with pytest.raises(ValueError):
            AgentSpec(name="x", budget={"max_per_run_usd": 0})


class TestFactory:
    def test_builds_an_agent_with_its_tools(self):
        spec = AgentSpec(
            name="Support",
            instructions="Be helpful.",
            capabilities=[{"id": "clock"}, {"id": "knowledge"}],
        )
        built = build_agent(
            spec,
            _model_spec(),
            organization_id=uuid.uuid4(),
            granted_scopes=frozenset({"knowledge:read"}),
            resources={"kb_collection_names": ["kb_1"]},
        )
        assert built.model_label == "GPT-4.1 (prod)"
        assert [type(c).__name__ for c in built.capabilities] == ["Clock", "Knowledge"]

    def test_agent_settings_override_the_profile(self):
        """The agent is the more specific statement of intent."""
        spec = AgentSpec(name="x", model_settings={"temperature": 0.9})
        built = build_agent(
            spec,
            _model_spec({"temperature": 0.1, "max_tokens": 100}),
            organization_id=uuid.uuid4(),
        )
        settings = built.agent.model_settings
        assert settings is not None
        assert settings["temperature"] == 0.9
        assert settings["max_tokens"] == 100

    def test_ungranted_scope_stops_the_build(self):
        spec = AgentSpec(name="x", capabilities=[{"id": "knowledge"}])
        with pytest.raises(BadRequestError):
            build_agent(
                spec, _model_spec(), organization_id=uuid.uuid4(), granted_scopes=frozenset()
            )

    def test_invalid_tool_config_stops_the_build(self):
        spec = AgentSpec(
            name="x", capabilities=[{"id": "knowledge", "config": {"default_top_k": 999}}]
        )
        with pytest.raises(BadRequestError):
            build_agent(
                spec,
                _model_spec(),
                organization_id=uuid.uuid4(),
                granted_scopes=frozenset({"knowledge:read"}),
            )

    def test_disabled_capabilities_are_not_built(self):
        spec = AgentSpec(
            name="x",
            capabilities=[{"id": "knowledge", "enabled": False}],
        )
        built = build_agent(
            spec,
            _model_spec(),
            organization_id=uuid.uuid4(),
            granted_scopes=frozenset({"knowledge:read"}),
            resources={"kb_collection_names": ["kb_1"]},
        )
        assert built.capabilities == []


class TestBudgetComposition:
    """Every ceiling a run is under, as its own entry with its own lookup.

    The agent's monthly cap and the organization's used to be collapsed with
    ``min()`` and checked against a single organization-wide total, which made
    ``AgentSpec.budget.monthly_usd`` a cap on the organization: an agent with a
    $10 limit was refused because its neighbours had spent $10. Two caps, two
    quantities - so what these assert is not one number but which lookup each
    cap ended up holding.
    """

    @staticmethod
    def _limits(built) -> list[tuple[str, Decimal]]:
        return [(limit.scope, limit.limit_usd) for limit in built.budget.limits]

    @staticmethod
    def _lookups(built) -> dict[str, object]:
        return {limit.scope: limit.period_spend for limit in built.budget.limits}

    def test_org_limit_applies_when_the_agent_sets_none(self):
        built = build_agent(
            AgentSpec(name="x"),
            _model_spec(),
            organization_id=uuid.uuid4(),
            org_monthly_budget_usd=Decimal("40"),
        )
        assert self._limits(built) == [("Organization monthly", Decimal("40"))]

    def test_an_agent_may_tighten_but_not_loosen_the_org_limit(self):
        """Both stand at their own number, and both are enforced.

        A $100 agent under a $40 ceiling is not "a $40 agent": its own cap is
        still $100 on its own spend, and the organization's $40 is what stops it
        - because the agent's spend is part of the organization's, so the
        organization's entry always binds first when it is the smaller of the
        two. That is the tighten-never-loosen rule, kept without a ``min()``.
        """
        loosening = build_agent(
            AgentSpec(name="x", budget={"monthly_usd": 100}),
            _model_spec(),
            organization_id=uuid.uuid4(),
            org_monthly_budget_usd=Decimal("40"),
        )
        assert self._limits(loosening) == [
            ("Agent monthly", Decimal("100")),
            ("Organization monthly", Decimal("40")),
        ]

        tightening = build_agent(
            AgentSpec(name="x", budget={"monthly_usd": 10}),
            _model_spec(),
            organization_id=uuid.uuid4(),
            org_monthly_budget_usd=Decimal("40"),
        )
        assert self._limits(tightening) == [
            ("Agent monthly", Decimal("10")),
            ("Organization monthly", Decimal("40")),
        ]

    @pytest.mark.anyio
    async def test_each_monthly_cap_holds_the_lookup_that_meters_it(self):
        """The defect, at the seam where it was introduced.

        One lookup handed to both caps is what made an agent's limit answerable
        by its neighbours' spending, and the two are indistinguishable by their
        numbers alone - only by which callable each one carries.
        """
        agent_spend = AsyncMock(return_value=Decimal("1"))
        org_spend = AsyncMock(return_value=Decimal("2"))
        built = build_agent(
            AgentSpec(name="x", budget={"monthly_usd": 10}),
            _model_spec(),
            organization_id=uuid.uuid4(),
            agent_period_spend=agent_spend,
            org_period_spend=org_spend,
            org_monthly_budget_usd=Decimal("40"),
        )

        lookups = self._lookups(built)
        assert await lookups["Agent monthly"]() == Decimal("1")
        assert await lookups["Organization monthly"]() == Decimal("2")

    def test_the_per_run_cap_meters_this_run_rather_than_a_period(self):
        """No lookup at all: the ledger the guard writes is exact and free.

        That is the one genuine difference between the caps, and it is expressed
        by the limit carrying no ``period_spend`` - not by the per-run cap being
        a different kind of thing. The exposure's per-run cap has always said it
        this way.
        """
        built = build_agent(
            AgentSpec(name="x", budget={"max_per_run_usd": 0.1, "monthly_usd": 10}),
            _model_spec(),
            organization_id=uuid.uuid4(),
            agent_period_spend=AsyncMock(return_value=Decimal("0")),
        )

        assert self._limits(built) == [("Run", Decimal("0.1")), ("Agent monthly", Decimal("10"))]
        assert self._lookups(built)["Run"] is None

    def test_budgets_are_decimal_not_float(self):
        """Money accumulated as float drifts; the boundary ends here."""
        built = build_agent(
            AgentSpec(name="x", budget={"max_per_run_usd": 0.1}),
            _model_spec(),
            organization_id=uuid.uuid4(),
        )
        assert self._limits(built) == [("Run", Decimal("0.1"))]

    def test_an_agent_with_no_budget_under_an_uncapped_org_is_unlimited(self):
        """Nothing to enforce is nothing to look up - and no round trip either."""
        built = build_agent(AgentSpec(name="x"), _model_spec(), organization_id=uuid.uuid4())

        assert built.budget.limits == []

    def test_caps_a_surface_adds_come_after_the_ones_the_spec_implies(self):
        """Narrowest first, so the refusal names the ceiling nearest the reader."""
        built = build_agent(
            AgentSpec(name="x", budget={"monthly_usd": 10}),
            _model_spec(),
            organization_id=uuid.uuid4(),
            org_monthly_budget_usd=Decimal("40"),
            extra_limits=[SpendLimit(scope="Exposure run", limit_usd=Decimal("0.5"))],
        )

        assert self._limits(built) == [
            ("Agent monthly", Decimal("10")),
            ("Organization monthly", Decimal("40")),
            ("Exposure run", Decimal("0.5")),
        ]


class TestMaxSteps:
    """A cap on model requests - what stops a tool loop that a budget only bills for."""

    def test_a_spec_that_says_nothing_runs_under_the_platform_default(self):
        # The default matches Pydantic AI's own, so making the limit explicit
        # did not change what every existing agent was already running under.
        built = build_agent(AgentSpec(name="a"), _model_spec(), organization_id=uuid.uuid4())

        assert built.usage_limits.request_limit == DEFAULT_MAX_STEPS

    def test_the_spec_decides_when_it_says(self):
        built = build_agent(
            AgentSpec(name="a", max_steps=8), _model_spec(), organization_id=uuid.uuid4()
        )

        assert built.usage_limits.request_limit == 8

    def test_zero_steps_is_refused_rather_than_stored(self):
        # An agent that may make no model request is an agent that cannot answer;
        # storing it produces a published agent that fails on its first turn.
        with pytest.raises(ValidationError):
            AgentSpec(name="a", max_steps=0)
