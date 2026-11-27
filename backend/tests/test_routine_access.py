"""A routine's access review, unit by unit: what each tool gets, and who may choose it.

See `docs/design/routine-access.md`. The service paths that need a database are
in `tests/integration/`.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.capabilities import get as capability
from app.agents.spec import AgentSpec, CapabilityBindingSpec, PlatformMcpServerRef
from app.core.audit import set_impersonator
from app.core.permissions import AuthContext
from app.schemas.routine_access import (
    RoutineAccessUpdate,
    RoutineCapabilityToolOption,
    RoutineMcpToolOption,
    RoutinePlatformToolOption,
)
from app.schemas.routine_sources import RoutineSourcePolicy
from app.schemas.routine_tool_keys import (
    MAX_ROUTINE_TOOLS,
    RoutineCapabilityToolKey,
    RoutineCapabilityToolSetting,
    RoutineMcpToolKey,
    RoutineMcpToolSetting,
    RoutinePlatformToolKey,
    RoutinePlatformToolSetting,
)
from app.services import routine_access
from app.services.routine_access import (
    INBOX_FINDING,
    allow_blocked,
    allow_holds,
    asks_for_routine,
    capability_tool_options,
    default_setting,
    in_console,
    platform_tool_options,
    provider_executed,
    routine_effect,
    setting_key,
    settings_of,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _policy(**update: object) -> RoutineSourcePolicy:
    return RoutineSourcePolicy(
        id=uuid4(),
        consented_by=uuid4(),
        reviewed_at=datetime.now(UTC),
        version_id=uuid4(),
        scope_hash="a" * 64,
        spec_hash="b" * 64,
    ).model_copy(update=update)


def _option(*, effect: bool, agent: str = "free") -> RoutineCapabilityToolOption:
    return RoutineCapabilityToolOption(
        capability_id="sandbox",
        capability_name="Sandbox",
        tool_id="execute",
        name="execute",
        effect=effect,
        agent=agent,
    )


def _ctx(role: str = "owner", **update: object) -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=role, **update)


def test_each_kind_of_setting_and_option_names_the_same_tool() -> None:
    connection = uuid4()
    capability_key = RoutineCapabilityToolKey(capability_id="sandbox", tool_id="execute")
    mcp_key = RoutineMcpToolKey(connection_id=connection, tool_id="create_issue")
    platform_key = RoutinePlatformToolKey(kind="platform", tool_id="create_task")
    assert setting_key(_option(effect=True)) == capability_key
    assert (
        setting_key(
            RoutineMcpToolOption(
                connection_id=connection,
                tool_id="create_issue",
                name="create_issue",
                account_name="GitHub",
                account_scope="personal",
                effect=True,
                agent="free",
            )
        )
        == mcp_key
    )
    assert (
        setting_key(
            RoutinePlatformToolOption(
                kind="platform",
                tool_id="create_task",
                name="create_task",
                group="tasks",
                effect=True,
                agent="free",
            )
        )
        == platform_key
    )
    policy = _policy(
        tools=(
            RoutineCapabilityToolSetting(**capability_key.model_dump(), setting="off"),
            RoutineMcpToolSetting(**mcp_key.model_dump(), setting="ask"),
            RoutinePlatformToolSetting(**platform_key.model_dump(), setting="allow"),
        )
    )
    assert settings_of(policy) == {capability_key: "off", mcp_key: "ask", platform_key: "allow"}
    # The private builder is the inverse: a key and a value back to a stored setting.
    assert [
        routine_access._setting(key, value) for key, value in settings_of(policy).items()
    ] == list(policy.tools)


@pytest.mark.parametrize(
    ("effect", "agent", "can_allow", "expected"),
    [
        (False, "free", False, "allow"),
        (False, "ask", True, "ask"),
        (True, "free", True, "allow"),
        (True, "free", False, "ask"),
        (True, "ask", True, "ask"),
    ],
)
def test_a_new_review_lets_run_what_the_creator_may_let_run(
    effect: bool, agent: str, can_allow: bool, expected: str
) -> None:
    assert default_setting(_option(effect=effect, agent=agent), can_allow=can_allow) == expected


@pytest.mark.parametrize(
    ("agent", "effect", "mode", "grandfathered", "setting", "can_allow", "asks"),
    [
        # The agent's own approval is the agent's, not the routine's.
        ("ask", True, "reviewed", False, "ask", True, False),
        # Off hides the tool; nothing waits for it.
        ("free", True, "reviewed", False, "off", True, False),
        ("free", False, "reviewed", False, "ask", True, True),
        ("free", True, "trust_agent", False, "ask", True, True),
        ("free", True, "trust_agent", False, None, False, False),
        ("free", False, "reviewed", False, None, False, False),
        ("free", True, "reviewed", False, "allow", True, False),
        # An allow the creator may no longer give asks again.
        ("free", True, "reviewed", False, "allow", False, True),
        ("free", True, "reviewed", True, "allow", False, False),
        # A tool added since the review asks, unless migrated from the agent's settings.
        ("free", True, "reviewed", False, None, True, True),
        ("free", True, "reviewed", True, None, False, False),
    ],
)
def test_the_routine_makes_a_tool_wait_only_where_its_review_does(
    agent: str,
    effect: bool,
    mode: str,
    grandfathered: bool,
    setting: str | None,
    can_allow: bool,
    asks: bool,
) -> None:
    policy = _policy(mode=mode, grandfathered=grandfathered)
    assert (
        asks_for_routine(
            _option(effect=effect, agent=agent),
            policy,
            setting,
            can_allow=can_allow,
        )
        is asks
    )


def test_tools_that_change_something_as_a_routine_counts_them() -> None:
    mirage = capability("mirage")
    sandbox = capability("sandbox")
    subagents = capability("subagents")
    tools = {
        (definition.id, tool.id): tool
        for definition in (mirage, sandbox, subagents)
        for tool in definition.tools
    }
    assert routine_effect(mirage, tools[("mirage", "mirage_write_file")], local=False)
    assert not routine_effect(mirage, tools[("mirage", "mirage_read_file")], local=False)
    # Writing a sandbox file is a write only on the creator's own computer.
    assert routine_effect(sandbox, tools[("sandbox", "write_file")], local=True)
    assert not routine_effect(sandbox, tools[("sandbox", "write_file")], local=False)
    assert routine_effect(sandbox, tools[("sandbox", "execute")], local=False)
    # A delegated task may cross a boundary nobody here can inspect.
    assert routine_effect(subagents, tools[("subagents", "task")], local=False)
    assert not routine_effect(subagents, tools[("subagents", "check_task")], local=False)
    assert routine_effect(subagents, tools[("subagents", "send_message_to_subagent")], local=False)


def test_a_provider_executed_tool_is_not_offered_and_a_disabled_capability_offers_nothing() -> None:
    spec = AgentSpec(
        name="Researcher",
        capabilities=[
            CapabilityBindingSpec(id="sandbox", tool_approval={"execute": "required"}),
            CapabilityBindingSpec(id="web_research", config={"method": "native"}),
            CapabilityBindingSpec(id="charts", enabled=False),
        ],
    )
    assert provider_executed(spec) == {
        RoutineCapabilityToolKey(capability_id="web_research", tool_id="web_search")
    }
    options = {option.tool_id: option for option in capability_tool_options(spec, local=False)}
    assert "web_search" not in options
    assert "create_chart" not in options
    assert options["execute"].effect is True and options["execute"].agent == "ask"
    assert options["read_file"].effect is False and options["read_file"].agent == "free"
    assert options["write_file"].effect is False
    local = {option.tool_id: option for option in capability_tool_options(spec, local=True)}
    assert local["write_file"].effect is True


def test_a_search_the_deployment_runs_itself_is_offered() -> None:
    spec = AgentSpec(name="Researcher", capabilities=[CapabilityBindingSpec(id="web_research")])
    assert provider_executed(spec) == set()
    assert [option.tool_id for option in capability_tool_options(spec, local=False)] == [
        "web_search"
    ]


def test_platform_tools_are_offered_only_to_a_routine_acting_as_its_creator() -> None:
    assert platform_tool_options(AgentSpec(name="Plain"), as_creator=True) == []
    spec = AgentSpec(
        name="Operator",
        instructions="Operate the platform.",
        mcp_servers=[PlatformMcpServerRef(account="platform")],
    )
    assert platform_tool_options(spec, as_creator=False) == []
    offered = platform_tool_options(spec, as_creator=True)
    assert offered
    # The routine's own report is never something to turn off.
    assert INBOX_FINDING not in {option.tool_id for option in offered}
    assert any(option.effect for option in offered)
    assert any(not option.effect for option in offered)


@pytest.mark.parametrize(
    "update",
    [
        {"api_key_id": uuid4()},
        {"routine_id": uuid4()},
        {"fired_as_creator": "schedule"},
        {"subject_is_publisher_fallback": True},
    ],
)
async def test_only_a_person_in_the_console_may_let_a_tool_run_freely(update: dict) -> None:
    ctx = _ctx(**update)
    assert not in_console(ctx)
    assert await allow_blocked(AsyncMock(), ctx) == "console"


async def test_an_impersonated_session_is_not_the_person_in_the_console() -> None:
    set_impersonator(uuid4())
    try:
        assert not in_console(_ctx())
    finally:
        set_impersonator(None)
    assert in_console(_ctx())


@pytest.mark.parametrize(
    ("role", "organization", "reason"),
    [
        ("builder", SimpleNamespace(chat_may_waive_approvals=True), "permission"),
        ("owner", None, "organization"),
        ("owner", SimpleNamespace(chat_may_waive_approvals=False), "organization"),
        ("owner", SimpleNamespace(chat_may_waive_approvals=True), None),
    ],
)
async def test_allowing_an_effect_needs_approvals_decide_and_the_organizations_consent(
    monkeypatch: pytest.MonkeyPatch, role: str, organization: object, reason: str | None
) -> None:
    monkeypatch.setattr(
        routine_access.organization_repo, "get_by_id", AsyncMock(return_value=organization)
    )
    assert await allow_blocked(AsyncMock(), _ctx(role)) == reason


@pytest.mark.parametrize(
    ("member", "holds"),
    [
        (None, False),
        (SimpleNamespace(role="builder"), False),
        (SimpleNamespace(role="owner"), True),
    ],
)
async def test_a_creators_allow_holds_at_call_time_only_while_they_still_may(
    monkeypatch: pytest.MonkeyPatch, member: object, holds: bool
) -> None:
    monkeypatch.setattr(routine_access.member_repo, "get_active", AsyncMock(return_value=member))
    monkeypatch.setattr(
        routine_access.organization_repo,
        "get_by_id",
        AsyncMock(return_value=SimpleNamespace(chat_may_waive_approvals=True)),
    )
    assert await allow_holds(AsyncMock(), organization_id=uuid4(), user_id=uuid4()) is holds


def test_a_review_names_at_most_the_supported_number_of_tools() -> None:
    setting = RoutineCapabilityToolSetting(
        capability_id="sandbox", tool_id="execute", setting="ask"
    )
    assert len(
        RoutineAccessUpdate(review_token="c" * 64, tools=[setting] * MAX_ROUTINE_TOOLS).tools
    ) == (MAX_ROUTINE_TOOLS)
    with pytest.raises(ValidationError, match="at most"):
        RoutineAccessUpdate(review_token="c" * 64, tools=[setting] * (MAX_ROUTINE_TOOLS + 1))
    with pytest.raises(ValidationError):
        RoutineAccessUpdate(review_token="c" * 64, mode="follow_agent")
