"""What a routine's access review decides about one tool call, on top of the agent's own gate.

See `docs/design/routine-access.md#deciding-one-tool-call`. A routine never
releases an approval its agent, a connection or the platform requires: those
floors are the `ApprovalGate`'s, and the tests below run through it where that
is the point.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic_ai import ApprovalRequired
from pydantic_ai.tools import ToolDefinition
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.approval import ApprovalPending
from app.agents.capabilities.approval import ApprovalGate
from app.agents.mcp import ALWAYS_ASKS, PLATFORM_TOOL
from app.agents.routine_actions import RoutineToolDecision
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import AuthorizationError
from app.db.models.agent_trigger import AgentTrigger
from app.schemas.routine_sources import RoutineSourcePolicy
from app.schemas.routine_tool_keys import RoutineCapabilityToolSetting, RoutineToolSettingValue
from app.services.routine_authority import RoutineAuthority
from app.services.routine_sources import RoutineSourcesRequired, source_scope
from tests.test_approval_gate import _call, _ctx, _Recorder

pytestmark = [pytest.mark.anyio, pytest.mark.security]

SPEC = AgentSpec(
    name="Worker",
    capabilities=[CapabilityBindingSpec(id="sandbox"), CapabilityBindingSpec(id="channel_actions")],
)
EXECUTE = ToolDefinition(name="execute", capability_id="sandbox")
READ = ToolDefinition(name="read_file", capability_id="sandbox")


def routine(
    *,
    mode: str = "reviewed",
    setting: RoutineToolSettingValue | None = None,
    delegates: str = "ask",
    grandfathered: bool = False,
    routine_kind: str = "trigger",
    tool: tuple[str, str] = ("sandbox", "execute"),
) -> tuple[RoutineAuthority, AgentTrigger]:
    """A routine admitted with a review giving `tool` the setting, and its stored row."""
    person, organization, agent = uuid4(), uuid4(), uuid4()
    trigger = AgentTrigger(
        id=uuid4(),
        organization_id=organization,
        agent_id=agent,
        created_by_user_id=person,
        trigger_type="schedule",
        prompt="Tidy the workspace",
        is_active=True,
        result_mode="report",
        runs_as_creator=True,
    )
    policy = RoutineSourcePolicy(
        mode=mode,
        tools=()
        if setting is None
        else (
            RoutineCapabilityToolSetting(capability_id=tool[0], tool_id=tool[1], setting=setting),
        ),
        delegates=delegates,
        grandfathered=grandfathered,
        id=uuid4(),
        consented_by=person,
        reviewed_at=datetime.now(UTC),
        version_id=uuid4(),
        scope_hash=source_scope(trigger),
        spec_hash="b" * 64,
    )
    trigger.approved_sources = policy.model_dump(mode="json")
    authority = RoutineAuthority(
        routine_id=trigger.id,
        organization_id=organization,
        user_id=person,
        root_agent_id=agent,
        role="owner",
        acts_as_creator=True,
        routine_kind=routine_kind,
        source_policy=policy if routine_kind == "trigger" else None,
    )
    return authority, trigger


async def decide(
    authority: RoutineAuthority,
    trigger: AgentTrigger,
    tool: ToolDefinition,
    *,
    agent_id: UUID | None = None,
    spec: AgentSpec = SPEC,
    holds: bool = True,
) -> RoutineToolDecision:
    db = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def context() -> AsyncIterator[AsyncSession]:
        yield db

    with (
        patch("app.services.routine_authority.get_db_context", context),
        patch.object(RoutineAuthority, "check_in", AsyncMock()),
        patch(
            "app.services.routine_authority.agent_trigger_repo.get",
            AsyncMock(return_value=trigger),
        ),
        patch("app.services.routine_authority.allow_holds", AsyncMock(return_value=holds)),
    ):
        return await authority.action_policy(agent_id or authority.root_agent_id, spec, tool)


async def test_off_refuses_the_call_in_either_mode() -> None:
    for mode in ("reviewed", "trust_agent"):
        authority, trigger = routine(mode=mode, setting="off")
        with pytest.raises(AuthorizationError, match="turned off"):
            await decide(authority, trigger, EXECUTE)


@pytest.mark.parametrize("mode", ["reviewed", "trust_agent"])
async def test_ask_asks_whatever_the_mode_and_the_creator_may(mode: str) -> None:
    authority, trigger = routine(mode=mode, setting="ask")
    assert await decide(authority, trigger, EXECUTE) == RoutineToolDecision(required=True)


@pytest.mark.parametrize(
    ("setting", "grandfathered", "holds", "expected"),
    [
        ("allow", False, True, "consented"),
        # Allowed, but the creator lost the permission or the organization withdrew it.
        ("allow", False, False, "asks"),
        # A tool added since the review asks.
        (None, False, True, "asks"),
        # Migrated from the agent's own settings: as before, without the check.
        (None, True, False, "free"),
        ("allow", True, False, "free"),
    ],
)
async def test_a_reviewed_routine_runs_an_effect_freely_only_as_its_creator_allowed(
    setting: RoutineToolSettingValue | None, grandfathered: bool, holds: bool, expected: str
) -> None:
    authority, trigger = routine(setting=setting, grandfathered=grandfathered)
    decision = await decide(authority, trigger, EXECUTE, holds=holds)
    assert (
        decision
        == {
            "consented": RoutineToolDecision(required=True, consented_by=authority.user_id),
            "asks": RoutineToolDecision(required=True),
            "free": RoutineToolDecision(),
        }[expected]
    )


@pytest.mark.parametrize("mode", ["reviewed", "trust_agent"])
async def test_a_read_runs_without_the_routine_asking(mode: str) -> None:
    authority, trigger = routine(mode=mode)
    assert await decide(authority, trigger, READ) == RoutineToolDecision()


async def test_a_trusting_routine_leaves_an_effect_to_the_agent() -> None:
    authority, trigger = routine(mode="trust_agent")
    assert await decide(authority, trigger, EXECUTE, holds=False) == RoutineToolDecision()


@pytest.mark.parametrize(
    ("mode", "delegates", "holds", "expected"),
    [
        ("reviewed", "ask", True, "asks"),
        ("reviewed", "allow", True, "consented"),
        ("reviewed", "allow", False, "asks"),
        ("trust_agent", "ask", False, "free"),
    ],
)
async def test_a_delegates_effect_follows_the_delegates_setting_not_the_root_tools(
    mode: str, delegates: str, holds: bool, expected: str
) -> None:
    # The root's `execute` is off; a delegate's own `execute` is not that tool.
    authority, trigger = routine(mode=mode, setting="off", delegates=delegates)
    decision = await decide(authority, trigger, EXECUTE, agent_id=uuid4(), holds=holds)
    assert (
        decision
        == {
            "consented": RoutineToolDecision(required=True, consented_by=authority.user_id),
            "asks": RoutineToolDecision(required=True),
            "free": RoutineToolDecision(),
        }[expected]
    )


async def test_a_capability_tool_outside_the_declared_catalog_asks_even_when_allowed() -> None:
    authority, trigger = routine(setting="allow", delegates="allow")
    guessed = ToolDefinition(name="execute_anything", capability_id="sandbox")
    assert await decide(authority, trigger, guessed) == RoutineToolDecision(required=True)


async def test_the_routines_own_report_never_asks() -> None:
    authority, trigger = routine()
    report = ToolDefinition(name="agenticos_publish_inbox_finding", metadata={PLATFORM_TOOL: True})
    assert await decide(authority, trigger, report) == RoutineToolDecision()


async def test_a_watch_asks_for_every_effect_and_reads_freely() -> None:
    authority, trigger = routine(routine_kind="watch")
    assert await decide(authority, trigger, EXECUTE) == RoutineToolDecision(required=True)
    assert await decide(authority, trigger, READ) == RoutineToolDecision()


async def test_a_review_saved_again_mid_run_stops_the_run() -> None:
    authority, trigger = routine(setting="allow")
    _, resaved = routine(setting="allow")
    trigger.approved_sources = resaved.approved_sources
    with pytest.raises(RoutineSourcesRequired):
        await decide(authority, trigger, EXECUTE)


@pytest.mark.parametrize(
    ("gate_kind", "mode", "setting"),
    [
        ("free", "trust_agent", None),
        ("free", "reviewed", "allow"),
        ("agent_required", "trust_agent", None),
        ("agent_required", "reviewed", "allow"),
        ("mandatory_platform", "trust_agent", None),
        ("reporter_free", "reviewed", None),
        ("reporter_required", "reviewed", None),
    ],
)
async def test_the_agent_and_mandatory_gates_still_ask_whatever_the_routine_allows(
    gate_kind: str, mode: str, setting: RoutineToolSettingValue | None
) -> None:
    authority, trigger = routine(
        mode=mode, setting=setting, tool=("channel_actions", "send_chat_message")
    )
    name = (
        "agenticos_publish_inbox_finding"
        if gate_kind.startswith("reporter")
        else "agenticos_publish_workflow"
        if gate_kind == "mandatory_platform"
        else "send_chat_message"
    )
    definition = ToolDefinition(
        name=name,
        capability_id=None if gate_kind == "mandatory_platform" else "channel_actions",
        metadata={PLATFORM_TOOL: True}
        if gate_kind.startswith("reporter")
        else {ALWAYS_ASKS: True}
        if gate_kind == "mandatory_platform"
        else None,
    )

    async def policy(tool: ToolDefinition) -> RoutineToolDecision:
        return await decide(authority, trigger, tool)

    gate = ApprovalGate(
        routine_policy=policy,
        required_tool_names=frozenset({name})
        if gate_kind in {"agent_required", "reporter_required"}
        else frozenset(),
    )
    ctx = _ctx(None)
    callback = AsyncMock(return_value=ApprovalPending())
    ctx.deps.request_approval = callback
    handler = _Recorder()
    if gate_kind == "free" and mode == "reviewed":
        # Allowed by the review: recorded as the creator's standing consent, not asked.
        with pytest.raises(ApprovalRequired):
            await gate.wrap_tool_execute(
                ctx, call=_call({}), tool_def=definition, args={}, handler=handler
            )
        assert callback.await_args.args[0].routine_consented_by == authority.user_id
    elif gate_kind in {"free", "reporter_free"}:
        assert (
            await gate.wrap_tool_execute(
                ctx, call=_call({}), tool_def=definition, args={}, handler=handler
            )
            == "sent"
        )
        assert handler.calls == [{}]
        callback.assert_not_awaited()
    else:
        with pytest.raises(ApprovalRequired):
            await gate.wrap_tool_execute(
                ctx, call=_call({}), tool_def=definition, args={}, handler=handler
            )
        assert handler.calls == []
        assert callback.await_args.args[0].routine_consented_by is None


def test_the_runs_tool_settings_are_its_admitted_reviews() -> None:
    from app.schemas.routine_tool_keys import RoutineCapabilityToolKey

    authority, _ = routine(setting="off")
    assert authority.tool_settings == {
        RoutineCapabilityToolKey(capability_id="sandbox", tool_id="execute"): "off"
    }
    watch, _ = routine(routine_kind="watch")
    assert watch.tool_settings == {}


@pytest.mark.parametrize(
    ("setting", "hidden"), [("off", True), ("ask", False), ("allow", False), (None, False)]
)
def test_only_off_hides_a_tool_from_the_model(
    setting: RoutineToolSettingValue | None, hidden: bool
) -> None:
    authority, _ = routine(setting=setting)
    [off] = authority.tools_off(SPEC) or [None]
    assert (off is not None and off.hidden(EXECUTE)) is hidden
    if off is not None:
        assert not off.hidden(READ)


@pytest.mark.parametrize("setting", ["off", "ask"])
def test_a_setting_on_a_tool_the_provider_runs_stops_the_run(
    setting: RoutineToolSettingValue,
) -> None:
    authority, _ = routine(setting=setting, tool=("web_research", "web_search"))
    native = AgentSpec(
        name="Researcher",
        capabilities=[CapabilityBindingSpec(id="web_research", config={"method": "native"})],
    )
    with pytest.raises(AuthorizationError) as refused:
        authority.tools_off(native)
    assert refused.value.details == {"tools": ["web_search"]}
    # Allowing what the provider runs anyway asks nothing of this deployment.
    allowed, _ = routine(setting="allow", tool=("web_research", "web_search"))
    assert allowed.tools_off(native) == ()


@pytest.mark.parametrize(
    ("mode", "reviewed_behavior", "refused"),
    [("reviewed", True, True), ("trust_agent", True, False), ("reviewed", False, False)],
)
def test_changed_skill_instructions_stop_only_a_reviewed_routine_that_recorded_them(
    mode: str, reviewed_behavior: bool, refused: bool
) -> None:
    from app.db.models.skill import Skill
    from app.services.routine_sources import materialized_behavior

    skill = Skill(id=uuid4(), name="policy", description="Policy", content="Approved", resources=[])
    changed = Skill(
        id=skill.id, name="policy", description="Policy", content="Unreviewed", resources=[]
    )
    from dataclasses import replace

    authority, _ = routine(mode=mode)
    assert authority.source_policy is not None
    authority = replace(
        authority,
        source_policy=authority.source_policy.model_copy(
            update={"behavior": materialized_behavior([skill], []) if reviewed_behavior else None}
        ),
    )
    authority.require_materialized([skill], [])
    if refused:
        with pytest.raises(RoutineSourcesRequired):
            authority.require_materialized([changed], [])
    else:
        authority.require_materialized([changed], [])


async def test_the_runs_own_tool_search_is_a_read() -> None:
    authority, trigger = routine()
    assert await decide(authority, trigger, ToolDefinition(name="search_tools")) == (
        RoutineToolDecision()
    )


@pytest.mark.parametrize(
    ("setting", "read_only", "expected"),
    [
        ("allow", False, "consented"),
        (None, False, "asks"),
        ("ask", True, "asks"),
        (None, True, "free"),
    ],
)
async def test_a_platform_tool_is_named_by_its_name_on_the_platforms_server(
    setting: RoutineToolSettingValue | None, read_only: bool, expected: str
) -> None:
    from app.services.routine_authority import _platform_tool_names

    called, name = next(iter(_platform_tool_names().items()))
    authority, trigger = routine(setting=None)
    policy = authority.source_policy
    assert policy is not None
    if setting is not None:
        from dataclasses import replace

        from app.schemas.routine_tool_keys import RoutinePlatformToolSetting

        reviewed = policy.model_copy(
            update={
                "tools": (
                    RoutinePlatformToolSetting(kind="platform", tool_id=name, setting=setting),
                )
            }
        )
        trigger.approved_sources = reviewed.model_dump(mode="json")
        authority = replace(authority, source_policy=reviewed)
    tool = ToolDefinition(
        name=called,
        metadata={PLATFORM_TOOL: True, "annotations": {"readOnlyHint": read_only}},
    )
    assert (
        await decide(authority, trigger, tool)
        == {
            "consented": RoutineToolDecision(required=True, consented_by=authority.user_id),
            "asks": RoutineToolDecision(required=True),
            "free": RoutineToolDecision(),
        }[expected]
    )
