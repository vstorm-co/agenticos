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
from pydantic_ai._run_context import RunContext
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models import ModelRequestContext, ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage, RunUsage

from app.agents.capabilities import load_builtins
from app.agents.capabilities.budget import BudgetScope
from app.agents.capabilities.compaction import ReportContextSize
from app.agents.factory import DEFAULT_MAX_STEPS, build_agent
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import (
    AgentSpec,
    AlertAudience,
    AlertSpec,
    NotificationSpec,
)
from app.core.exceptions import BadRequestError
from app.core.secret_kinds import ApiKeySecret


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


def _run_context() -> RunContext[None]:
    return RunContext(deps=None, model=TestModel(), usage=RunUsage())


def _request_context() -> ModelRequestContext:
    return ModelRequestContext(
        model=TestModel(),
        messages=[],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    )


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
            AgentSpec(name="x", budget={"monthly_usd": 0})

    def test_a_per_run_cap_is_no_longer_a_thing_a_spec_can_say(self):
        """The platform has exactly two budget levels - the agent's month and
        the organization's. A spec still carrying the old key must fail loudly
        at validation, which is what the 0062 data migration exists to prevent
        for rows written before the key was removed."""
        with pytest.raises(ValueError):
            AgentSpec(name="x", budget={"max_per_run_usd": 1})


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

    @pytest.mark.anyio
    async def test_an_agent_that_binds_nothing_still_reports_its_context(self):
        """The gauge is attached whatever the spec says, and this is the point.

        An agent with no `compaction` binding is the one that reaches the context
        ceiling and is refused by the provider mid-answer - there is no strategy
        to save it, so the reading is the whole of what it gets. Bound to the
        capability list beside the budget guard rather than inside `*configured`,
        which is what makes it independent of the spec.
        """
        built = build_agent(
            AgentSpec(name="Bare", instructions="Be brief."),
            _model_spec(),
            organization_id=uuid.uuid4(),
        )

        attached: list[object] = []
        built.agent.root_capability.apply(attached.append)
        gauge = next(c for c in attached if isinstance(c, ReportContextSize))

        assert built.capabilities == []
        await gauge.after_model_request(
            _run_context(),
            request_context=_request_context(),
            response=ModelResponse(
                parts=[TextPart(content="ok")], usage=RequestUsage(input_tokens=41_806)
            ),
        )
        assert built.context.latest == 41_806

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
    `min()` and checked against a single organization-wide total, which made
    `AgentSpec.budget.monthly_usd` a cap on the organization: an agent with a
    $10 limit was refused because its neighbours had spent $10. Two caps, two
    quantities - so what these assert is not one number but which lookup each
    cap ended up holding.
    """

    @staticmethod
    def _limits(built) -> list[tuple[BudgetScope, Decimal]]:
        return [(limit.scope, limit.limit_usd) for limit in built.budget.limits]

    @staticmethod
    def _lookups(built) -> dict[BudgetScope, object]:
        return {limit.scope: limit.period_spend for limit in built.budget.limits}

    def test_org_limit_applies_when_the_agent_sets_none(self):
        built = build_agent(
            AgentSpec(name="x"),
            _model_spec(),
            organization_id=uuid.uuid4(),
            org_monthly_budget_usd=Decimal("40"),
        )
        assert self._limits(built) == [(BudgetScope.ORGANIZATION, Decimal("40"))]

    def test_an_agent_may_tighten_but_not_loosen_the_org_limit(self):
        """Both stand at their own number, and both are enforced.

        A $100 agent under a $40 ceiling is not "a $40 agent": its own cap is
        still $100 on its own spend, and the organization's $40 is what stops it
        - because the agent's spend is part of the organization's, so the
        organization's entry always binds first when it is the smaller of the
        two. That is the tighten-never-loosen rule, kept without a `min()`.
        """
        loosening = build_agent(
            AgentSpec(name="x", budget={"monthly_usd": 100}),
            _model_spec(),
            organization_id=uuid.uuid4(),
            org_monthly_budget_usd=Decimal("40"),
        )
        assert self._limits(loosening) == [
            (BudgetScope.AGENT, Decimal("100")),
            (BudgetScope.ORGANIZATION, Decimal("40")),
        ]

        tightening = build_agent(
            AgentSpec(name="x", budget={"monthly_usd": 10}),
            _model_spec(),
            organization_id=uuid.uuid4(),
            org_monthly_budget_usd=Decimal("40"),
        )
        assert self._limits(tightening) == [
            (BudgetScope.AGENT, Decimal("10")),
            (BudgetScope.ORGANIZATION, Decimal("40")),
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
        assert await lookups[BudgetScope.AGENT]() == Decimal("1")
        assert await lookups[BudgetScope.ORGANIZATION]() == Decimal("2")

    def test_budgets_are_decimal_not_float(self):
        """Money accumulated as float drifts; the boundary ends here."""
        built = build_agent(
            AgentSpec(name="x", budget={"monthly_usd": 0.1}),
            _model_spec(),
            organization_id=uuid.uuid4(),
        )
        assert self._limits(built) == [(BudgetScope.AGENT, Decimal("0.1"))]

    def test_an_agent_with_no_budget_under_an_uncapped_org_is_unlimited(self):
        """Nothing to enforce is nothing to look up - and no round trip either."""
        built = build_agent(AgentSpec(name="x"), _model_spec(), organization_id=uuid.uuid4())

        assert built.budget.limits == []

    def test_a_previewed_cap_meters_only_this_runs_ledger(self):
        """No database to ask on a preview, so the cap carries no lookup and
        binds on what this run alone has booked."""
        built = build_agent(
            AgentSpec(name="x", budget={"monthly_usd": 10}),
            _model_spec(),
            organization_id=uuid.uuid4(),
        )

        assert self._lookups(built)[BudgetScope.AGENT] is None


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


class TestWhoHearsAboutAnAgent:
    """The notification block, and the four configurations it refuses.

    Each refusal is a spec somebody would write believing they had set an alert
    up. Accepting any of them means an alert that resolves to nobody, or to
    exactly the people it would have reached anyway - and the only place that
    becomes visible is when the email everybody was relying on does not arrive.
    """

    def test_an_agent_published_before_this_existed_keeps_the_old_behaviour(self):
        """The whole point of a defaulted field: nothing stored has to be migrated."""
        spec = AgentSpec.model_validate({"name": "Legacy", "spec_version": 4})

        assert spec.notifications.budget.to == [AlertAudience.ADMINS, AlertAudience.OWNER]
        assert spec.notifications.approvals.to == [
            AlertAudience.INITIATOR,
            AlertAudience.ADMINS,
        ]
        # Off, because a per-agent report nobody asked for is one more weekly
        # email arriving for an agent that used to send none.
        assert spec.notifications.usage.enabled is False

    def test_naming_nobody_for_a_chosen_audience_is_refused(self):
        with pytest.raises(ValidationError, match="at least one member"):
            AlertSpec(to=[AlertAudience.CHOSEN])

    def test_naming_people_without_choosing_them_is_refused(self):
        """Ids with no `chosen` in `to` are ids nothing reads - which reads, in
        the Builder, exactly like a list of people who will be mailed."""
        with pytest.raises(ValidationError, match="only read when"):
            AlertSpec(to=[AlertAudience.ADMINS], user_ids=[uuid.uuid4()])

    def test_an_enabled_alert_with_no_audience_is_refused(self):
        with pytest.raises(ValidationError, match="at least one audience"):
            AlertSpec(enabled=True, to=[])

    def test_a_disabled_alert_needs_no_audience(self):
        """Switching an alert off is not the same as misconfiguring it."""
        assert AlertSpec(enabled=False, to=[]).enabled is False

    def test_a_usage_report_cannot_be_sent_to_the_initiator(self):
        """A report covers a period, not a run, so there is no such person - and an
        audience that silently contributes nothing is the failure being prevented."""
        with pytest.raises(ValidationError, match="no initiator"):
            NotificationSpec(usage=AlertSpec(to=[AlertAudience.INITIATOR]))

    def test_the_notification_block_survives_a_yaml_round_trip(self):
        """A spec is exported to a client's repository and read back."""
        spec = AgentSpec(
            name="Support",
            notifications=NotificationSpec(
                approvals=AlertSpec(to=[AlertAudience.CHOSEN], user_ids=[uuid.uuid4()])
            ),
        )

        assert AgentSpec.from_yaml(spec.to_yaml()) == spec

    def test_an_alert_audience_names_people_by_reference_never_by_address(self):
        """The spec's own first rule, applied to the one field that holds people.

        `AlertSpec` carries user ids. If it ever grew an `emails` field - which is
        the obvious shortcut for "mail this external stakeholder" - a spec exported
        as YAML into a client's git repository would carry their staff's addresses
        with it, and a spec imported into another organization would mail people
        who have nothing to do with it. Ids at least resolve to nobody outside the
        tenant, which is what `list_emails_for_members` enforces.
        """
        fields = set(AlertSpec.model_fields)

        assert fields == {"enabled", "to", "user_ids"}
        assert not any("mail" in name or "address" in name for name in fields)

    def test_a_rendered_spec_carries_no_address(self):
        """Belt and braces on the export path, because that is where it would be
        noticed last: a YAML file in somebody's repository."""
        spec = AgentSpec(
            name="Support",
            notifications=NotificationSpec(
                approvals=AlertSpec(to=[AlertAudience.CHOSEN], user_ids=[uuid.uuid4()])
            ),
        )

        assert "@" not in spec.to_yaml()
