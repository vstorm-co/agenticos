"""Tests for the agent spec and the factory that instantiates it.

The spec is the platform's most load-bearing type - the Builder writes it, the
database versions it, and clients commit it to their own repositories - so what
is guarded here is its contract: it round-trips, it refuses contradictions, and
it never carries a secret.
"""

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from pydantic_ai._run_context import RunContext
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models import ModelRequestContext, ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RequestUsage, RunUsage

from app.agents.capabilities import load_builtins
from app.agents.capabilities.approval._capability import ApprovalGate
from app.agents.capabilities.budget import BudgetScope
from app.agents.capabilities.compaction import ReportContextSize
from app.agents.factory import DEFAULT_MAX_STEPS, BuiltAgent, build_agent
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

    def test_an_earlier_turns_measurement_starts_the_gauge_off(self):
        """The gauge is per run and filled by a *response*, so on a one-request
        turn it is empty for the whole of it - and compaction, which reads it to
        decide whether the window has room for a summary at all, could never tell
        that case from a working one. The overhead is a property of the agent's
        instructions and tool schemas rather than of one run, so what an earlier
        turn measured is where this one starts (#49)."""
        built = build_agent(
            AgentSpec(name="Bare", instructions="Be brief."),
            _model_spec(),
            organization_id=uuid.uuid4(),
            recorded_overhead=3_865,
        )

        assert built.context.overhead == 3_865

    def test_a_thread_that_has_measured_nothing_starts_empty(self):
        """A first turn. Nothing is guessed here - a made-up overhead would move
        a refusal that costs an agent its compaction."""
        built = build_agent(
            AgentSpec(name="Bare", instructions="Be brief."),
            _model_spec(),
            organization_id=uuid.uuid4(),
        )

        assert built.context.overhead is None

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


class TestToolSearchDefersMcp:
    """Binding `tool_search` is what hides the MCP toolsets behind discovery.

    The capability and the deferral are two halves of one decision: `ToolSearch`
    is inert with nothing deferred, and a deferred toolset with no `ToolSearch`
    to find it is a set of tools the model can never call. So what is pinned here
    is the pairing - the MCP toolsets are deferred exactly when the capability is
    bound, and left alone when it is not.

    A `DeferredLoadingToolset` on the agent proves the wrapper is *present*; it
    does not prove the tools are actually hidden from the model, which is the
    whole point of the capability - one could exist and still leak every MCP
    schema through, and the wrapper assertions would stay green (#50). So the
    behaviour is pinned end to end with a `FunctionModel` that records the tools
    it is offered: when bound the MCP schemas are gone and `search_tools` stands
    in their place, and when unbound every schema is in front of the model.
    """

    @staticmethod
    def _mcp_toolset() -> FunctionToolset[Any]:
        """Two named tools standing in for the schemas an MCP server exposes."""
        toolset: FunctionToolset[Any] = FunctionToolset()

        def fetch_invoice(invoice_id: str) -> str:
            """Fetch an invoice by id."""
            return "invoice"

        def refund_payment(payment_id: str) -> str:
            """Refund a payment by id."""
            return "refunded"

        toolset.add_function(fetch_invoice, takes_ctx=False)
        toolset.add_function(refund_payment, takes_ctx=False)
        return toolset

    @classmethod
    def _agent_with_mcp(cls, capabilities: list[dict[str, Any]]) -> BuiltAgent:
        spec = AgentSpec(name="x", capabilities=capabilities)
        return build_agent(
            spec,
            _model_spec(),
            organization_id=uuid.uuid4(),
            extra_toolsets=[cls._mcp_toolset()],
        )

    @staticmethod
    async def _tools_the_model_sees(built: BuiltAgent) -> list[str]:
        """The function-tool names put in front of the model on its first request."""
        seen: list[list[str]] = []

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            seen.append([tool.name for tool in info.function_tools])
            return ModelResponse(parts=[TextPart("noted")])

        with built.agent.override(model=FunctionModel(respond)):
            await built.agent.run("hello", deps=built.deps)
        return seen[0]

    def test_the_mcp_toolsets_are_deferred_when_it_is_bound(self):
        from pydantic_ai.toolsets.deferred_loading import DeferredLoadingToolset

        built = self._agent_with_mcp([{"id": "tool_search"}])

        assert any(isinstance(ts, DeferredLoadingToolset) for ts in built.agent.toolsets)

    def test_the_mcp_toolsets_are_untouched_when_it_is_not(self):
        """An agent that does not enable it pays nothing: its tools stay visible."""
        from pydantic_ai.toolsets.deferred_loading import DeferredLoadingToolset

        built = self._agent_with_mcp([])

        assert not any(isinstance(ts, DeferredLoadingToolset) for ts in built.agent.toolsets)

    @pytest.mark.anyio
    async def test_the_mcp_schemas_are_hidden_behind_search_when_bound(self):
        """The behaviour the wrapper only implies: on the first request the model
        is offered `search_tools` and none of the MCP schemas it exists to hide.

        `keywords` is chosen for determinism - it keeps the local `search_tools`
        function on the wire on every provider, where `auto` would defer to a
        provider-native builtin a `FunctionModel` does not implement and so offer
        the model nothing to capture.
        """
        built = self._agent_with_mcp([{"id": "tool_search", "config": {"strategy": "keywords"}}])

        offered = await self._tools_the_model_sees(built)

        assert offered == ["search_tools"]

    @pytest.mark.anyio
    async def test_every_mcp_schema_is_visible_when_it_is_not_bound(self):
        """The other direction: with nothing to defer to, every MCP schema is in
        front of the model on the first request and there is no `search_tools`."""
        built = self._agent_with_mcp([])

        offered = await self._tools_the_model_sees(built)

        assert offered == ["fetch_invoice", "refund_payment"]


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


class TestAskingAboutEveryTool:
    """`gate_every_tool` reaching the gate the factory installs.

    The middle link of the chain #1326 broke. The runner decides the flag from
    the mode a run was admitted on and the gate refuses a rejected call; between
    them is this, and an argument that stopped arriving here would silently undo
    both ends while each kept its own tests green.
    """

    @staticmethod
    def _gate(built: BuiltAgent) -> ApprovalGate:
        attached: list[object] = []
        built.agent.root_capability.apply(attached.append)
        return next(one for one in attached if isinstance(one, ApprovalGate))

    def test_the_flag_reaches_the_gate(self):
        built = build_agent(
            AgentSpec(name="Clerk"),
            _model_spec(),
            organization_id=uuid.uuid4(),
            gate_every_tool=True,
        )

        assert self._gate(built).gate_every_tool is True

    def test_it_is_off_unless_a_session_asked(self):
        built = build_agent(AgentSpec(name="Clerk"), _model_spec(), organization_id=uuid.uuid4())

        assert self._gate(built).gate_every_tool is False


class TestAnApprovalTheGateCouldNotEnforce:
    """A stored version whose approval the provider's own execution walks past.

    Publish validation refuses the combination, but a version published before
    that refusal existed never passes through it again: a run loads the frozen
    `AgentVersion` and hands its spec straight here. So without a refusal at
    assembly, every agent #839 and #857 were written for goes on fetching and
    searching unapproved (#871). These drive the stored spec, never
    `validate_spec`.
    """

    @staticmethod
    def _stored(capability: dict[str, Any]) -> AgentSpec:
        """A spec as a published version holds it: JSON, read back untouched."""
        return AgentSpec.model_validate({"name": "Researcher", "capabilities": [capability]})

    def _build(self, capability: dict[str, Any], scope: str) -> BuiltAgent:
        return build_agent(
            self._stored(capability),
            _model_spec(),
            organization_id=uuid.uuid4(),
            granted_scopes=frozenset({scope}),
        )

    def test_a_stored_native_search_with_approval_does_not_assemble(self):
        with pytest.raises(BadRequestError) as refused:
            self._build(
                {"id": "web_research", "config": {"method": "native"}, "approval": "required"},
                "web:read",
            )

        assert any("no call to hold" in problem for problem in refused.value.details["problems"])

    def test_a_stored_native_fetch_with_approval_does_not_assemble(self):
        """#839 refused this at publish and left every version published before it."""
        with pytest.raises(BadRequestError) as refused:
            self._build(
                {
                    "id": "web_fetch",
                    "config": {"method": "auto"},
                    "tool_approval": {"web_fetch": "required"},
                },
                "web:fetch",
            )

        assert any("no call to hold" in problem for problem in refused.value.details["problems"])

    def test_a_native_search_nobody_asked_to_approve_still_runs(self):
        """The refusal is about the approval, not about the provider searching."""
        built = self._build({"id": "web_research", "config": {"method": "native"}}, "web:read")

        assert len(built.capabilities) == 1

    def test_a_disabled_binding_is_not_a_reason_to_refuse(self):
        built = self._build(
            {
                "id": "web_research",
                "config": {"method": "native"},
                "approval": "required",
                "enabled": False,
            },
            "web:read",
        )

        assert built.capabilities == []


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
