"""Platform default exemptions remain narrower than an explicit human-approval policy."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets.abstract import ToolsetTool

from app.agents.mcp import (
    ALWAYS_ASKS,
    CONDITIONAL_EXECUTION,
    NEEDS_APPROVAL,
    ApprovalMarked,
    approval_needed,
)
from app.agents.spec import ApprovalMode, McpApproval


@pytest.mark.parametrize(
    ("policy", "own", "read_only", "default_allow", "expected"),
    [
        ("writes", "default", False, True, False),
        ("writes", "required", False, True, True),
        ("all", "default", False, True, True),
        ("all", "required", False, True, True),
        ("all", "never", False, True, False),
        ("writes", "never", False, True, False),
        ("writes", "default", False, False, True),
        ("writes", "default", True, False, False),
        ("none", "default", False, True, False),
        ("none", "required", False, True, True),
    ],
)
def test_default_write_exemption_preserves_explicit_policy(
    policy: McpApproval,
    own: ApprovalMode,
    read_only: bool,
    default_allow: bool,
    expected: bool,
) -> None:
    assert (
        approval_needed(policy, read_only=read_only, own=own, default_allow=default_allow)
        is expected
    )


@pytest.mark.anyio
@pytest.mark.security
@pytest.mark.parametrize("in_process", [True, False])
async def test_only_trusted_in_process_tools_receive_the_default_write_exemption(
    in_process: bool,
) -> None:
    inner = MagicMock()
    definition = ToolDefinition(
        name="agenticos_create_task",
        parameters_json_schema={"type": "object", "properties": {}},
        metadata={
            "annotations": {"readOnlyHint": False, "default_approval_free": True},
            "agenticos_default_approval_free": True,
            CONDITIONAL_EXECUTION: "create_task",
        },
    )
    inner.get_tools = AsyncMock(
        return_value={
            definition.name: ToolsetTool(
                toolset=inner, tool_def=definition, max_retries=1, args_validator=MagicMock()
            )
        }
    )
    marked = await ApprovalMarked(
        inner,
        policy="writes",
        in_process=in_process,
        default_approval_free=frozenset({definition.name}),
        conditional_execution={definition.name: "create_task"},
    ).get_tools(MagicMock())
    metadata = marked[definition.name].tool_def.metadata
    assert metadata is not None
    assert metadata[NEEDS_APPROVAL] is not in_process
    assert metadata["annotations"]["readOnlyHint"] is False
    assert metadata[CONDITIONAL_EXECUTION] == ("create_task" if in_process else None)


@pytest.mark.anyio
@pytest.mark.security
async def test_always_ask_floor_cannot_be_released_by_a_default_exemption_or_never_override() -> (
    None
):
    inner = MagicMock()
    definition = ToolDefinition(name="agenticos_update_virtual_table_schema")
    inner.get_tools = AsyncMock(
        return_value={
            definition.name: ToolsetTool(
                toolset=inner, tool_def=definition, max_retries=1, args_validator=MagicMock()
            )
        }
    )
    marked = await ApprovalMarked(
        inner,
        policy="none",
        in_process=True,
        tool_approval={definition.name: "never"},
        default_approval_free=frozenset({definition.name}),
        always_asks=frozenset({definition.name}),
    ).get_tools(MagicMock())
    metadata = marked[definition.name].tool_def.metadata
    assert metadata is not None
    assert metadata[ALWAYS_ASKS] is True
    assert metadata[NEEDS_APPROVAL] is True


@pytest.mark.parametrize(
    ("approval", "own", "expected"),
    [("writes", "default", True), ("all", "default", False), ("writes", "required", False)],
)
def test_routine_platform_consent_uses_the_same_default_write_policy(
    approval: McpApproval, own: ApprovalMode, expected: bool
) -> None:
    from app.agents.spec import AgentSpec, PlatformMcpServerRef
    from app.services.routine_actions import platform_action_options

    spec = AgentSpec(
        name="Tasks",
        instructions="Manage authorized tasks.",
        mcp_servers=[
            PlatformMcpServerRef(
                account="platform",
                approval=approval,
                allowed_tools=["create_task", "invite_member"],
                tool_approval={"create_task": own, "invite_member": "never"},
            )
        ],
    )
    options = {tool.tool_id: tool for tool in platform_action_options(spec, as_creator=True)}
    assert options["create_task"].waivable is expected
    assert options["invite_member"].waivable is False


def test_catalog_keeps_default_free_operations_marked_as_real_writes() -> None:
    from app.services.platform_mcp import platform_tool_catalog

    tools = {tool.name: tool for tool in platform_tool_catalog()}
    for name in (
        "create_task",
        "update_task",
        "add_virtual_table_record",
        "update_agent_draft",
        "prepare_solution",
    ):
        assert tools[name].writes is True
        assert tools[name].default_approval_free is True
        assert tools[name].ungated is False


@pytest.mark.security
def test_every_catalog_write_has_an_explicit_approval_classification() -> None:
    from app.core.platform_tool_policy import (
        ALWAYS_ASKS,
        CONDITIONAL_EXECUTION,
        DEFAULT_APPROVAL_FREE,
        UNGATED,
    )
    from app.services.platform_mcp import platform_tool_catalog

    writes = {tool.name for tool in platform_tool_catalog() if tool.writes}
    assert writes == ALWAYS_ASKS | DEFAULT_APPROVAL_FREE | UNGATED
    assert not ALWAYS_ASKS & DEFAULT_APPROVAL_FREE
    assert not UNGATED & (ALWAYS_ASKS | DEFAULT_APPROVAL_FREE)
    assert CONDITIONAL_EXECUTION <= DEFAULT_APPROVAL_FREE
    assert {
        "install_solution",
        "create_agent_environment",
        "update_agent_environment",
        "change_skill_version",
        "draft_knowledge_topic",
        "update_virtual_table_schema",
    } <= ALWAYS_ASKS


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["create_task", "update_task"])
@pytest.mark.parametrize(
    "status", ["planned", "in_progress", "waiting_for_user", "blocked", "done", "cancelled"]
)
@pytest.mark.parametrize("actor", ["user", "agent"])
async def test_only_active_agent_task_poststates_require_a_fresh_answer(
    name: str, status: str, actor: str
) -> None:
    from uuid import uuid4

    from app.agents.deps import AgentDeps
    from app.agents.platform_approval import may_schedule_agent_work

    task = {
        "title": "Review",
        "status": status,
        "next_actor": actor,
        "assignee_agent_id": str(uuid4()),
        "expected_revision": 2,
    }
    # TaskCreate rejects unknown revision fields, unlike TaskUpdate.
    if name == "create_task":
        del task["expected_revision"]
    assert await may_schedule_agent_work(name, AgentDeps(run_id=uuid4()), {"task": task}) is (
        actor == "agent" and status in {"planned", "in_progress"}
    )


@pytest.mark.anyio
async def test_create_task_implicit_agent_next_actor_is_not_an_execution_bypass() -> None:
    from uuid import uuid4

    from app.agents.deps import AgentDeps
    from app.agents.platform_approval import may_schedule_agent_work

    assert await may_schedule_agent_work(
        "create_task",
        AgentDeps(run_id=uuid4()),
        {"task": {"title": "Research", "assignee_agent_id": str(uuid4())}},
    )
    assert not await may_schedule_agent_work(
        "create_task", AgentDeps(run_id=uuid4()), {"task": {"title": "Human task"}}
    )


@pytest.mark.anyio
@pytest.mark.security
@pytest.mark.parametrize("trusted", [True, False])
async def test_conditional_floor_ignores_external_metadata_and_never_override(
    trusted: bool,
) -> None:
    from uuid import uuid4

    from app.agents.capabilities.approval import ApprovalGate
    from app.agents.deps import AgentDeps
    from app.agents.mcp import CONDITIONAL_EXECUTION, PLATFORM_TOOL

    ctx = MagicMock(deps=AgentDeps(run_id=uuid4()))
    definition = ToolDefinition(
        name="create_task",
        metadata={
            PLATFORM_TOOL: trusted,
            CONDITIONAL_EXECUTION: "create_task",
            NEEDS_APPROVAL: False,
        },
    )
    assert (
        await ApprovalGate()._always_asks(
            ctx, definition, {"task": {"title": "Research", "assignee_agent_id": str(uuid4())}}
        )
        is trusted
    )


@pytest.mark.anyio
@pytest.mark.security
async def test_failed_conditional_inspection_is_asked_not_silently_released() -> None:
    from uuid import uuid4

    from app.agents.capabilities.approval import ApprovalGate
    from app.agents.deps import AgentDeps
    from app.agents.mcp import CONDITIONAL_EXECUTION, PLATFORM_TOOL

    ctx = MagicMock(deps=AgentDeps(run_id=uuid4()))
    definition = ToolDefinition(
        name="create_task",
        metadata={PLATFORM_TOOL: True, CONDITIONAL_EXECUTION: "create_task", NEEDS_APPROVAL: False},
    )
    assert await ApprovalGate()._always_asks(
        ctx, definition, {"task": {"title": "Invalid", "next_actor": "agent"}}
    )


@pytest.mark.anyio
@pytest.mark.security
@pytest.mark.parametrize("operation", ["add", "update", "upsert"])
@pytest.mark.parametrize(
    "status,actor,expected",
    [
        ("planned", "agent", True),
        ("in_progress", "agent", True),
        ("done", "agent", False),
        ("blocked", "agent", False),
        ("waiting_for_user", "agent", False),
        ("cancelled", "agent", False),
        ("planned", "user", False),
    ],
)
async def test_generic_task_board_writes_cannot_bypass_agent_execution_floor(
    operation: str, status: str, actor: str, expected: bool
) -> None:
    from unittest.mock import patch
    from uuid import uuid4

    from app.schemas.task import TaskFields
    from app.services.task_columns import STATUSES, to_cells
    from app.services.tasks import TaskService

    board = MagicMock(
        column_ids={name: str(uuid4()) for name in TaskFields.model_fields},
        status_ids={name: str(uuid4()) for name in (*STATUSES, "actor:user", "actor:agent")},
    )
    values = to_cells(
        board,
        TaskFields.model_validate(
            {
                "title": "Task",
                "status": status,
                "next_actor": actor,
                "assignee_agent_id": str(uuid4()),
            }
        ),
    )
    table_id, record_id = uuid4(), uuid4()
    ctx = MagicMock()
    service = TaskService(MagicMock())
    service.tables = MagicMock(
        describe_table=AsyncMock(return_value=MagicMock(can_edit=True, columns=[]))
    )
    row = MagicMock(table_id=table_id, revision=3, values=values)
    with (
        patch("app.services.tasks.task_repo.for_table", new=AsyncMock(return_value=board)),
        patch("app.services.tasks.task_repo.record", new=AsyncMock(return_value=row)) as read,
    ):
        verdict = await service.record_may_schedule_agent_work(
            ctx, table_id, values, operation=operation, record_id=record_id, expected_revision=3
        )
    assert verdict is expected
    if operation == "update":
        read.assert_awaited_once_with(service.db, record_id, ctx.organization_id)
    else:
        read.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.security
async def test_record_preflight_checks_access_before_task_metadata_and_rejects_stale_revision() -> (
    None
):
    from unittest.mock import patch
    from uuid import uuid4

    from app.core.exceptions import AuthorizationError
    from app.services.tasks import TaskService

    service = TaskService(MagicMock())
    table_id, record_id = uuid4(), uuid4()
    service.tables = MagicMock(describe_table=AsyncMock(return_value=MagicMock(can_edit=False)))
    with patch("app.services.tasks.task_repo.for_table", new=AsyncMock()) as lookup:
        with pytest.raises(AuthorizationError):
            await service.record_may_schedule_agent_work(
                MagicMock(),
                table_id,
                {},
                operation="update",
                record_id=record_id,
                expected_revision=2,
            )
        lookup.assert_not_awaited()
    service.tables.describe_table.return_value.can_edit = True
    with (
        patch("app.services.tasks.task_repo.for_table", new=AsyncMock(return_value=MagicMock())),
        patch(
            "app.services.tasks.task_repo.record",
            new=AsyncMock(return_value=MagicMock(table_id=table_id, revision=3)),
        ),
    ):
        assert await service.record_may_schedule_agent_work(
            MagicMock(), table_id, {}, operation="update", record_id=record_id, expected_revision=2
        )


@pytest.mark.anyio
async def test_ordinary_tables_and_explicit_person_upserts_remain_default_free() -> None:
    from unittest.mock import patch
    from uuid import uuid4

    from app.services.tasks import TaskService

    service = TaskService(MagicMock())
    service.tables = MagicMock(describe_table=AsyncMock(return_value=MagicMock(can_edit=True)))
    with patch("app.services.tasks.task_repo.for_table", new=AsyncMock(return_value=None)):
        assert not await service.record_may_schedule_agent_work(
            MagicMock(), uuid4(), {}, operation="upsert"
        )
    board = MagicMock(
        column_ids={"next_actor": "actor", "status": "status"},
        status_ids={
            "actor:user": "person",
            "done": "done",
            "cancelled": "cancelled",
            "waiting_for_user": "waiting",
            "blocked": "blocked",
        },
    )
    with patch("app.services.tasks.task_repo.for_table", new=AsyncMock(return_value=board)):
        assert await service.record_may_schedule_agent_work(
            MagicMock(), uuid4(), {}, operation="upsert"
        )
        assert not await service.record_may_schedule_agent_work(
            MagicMock(), uuid4(), {"actor": "person"}, operation="upsert"
        )


@pytest.mark.anyio
@pytest.mark.security
@pytest.mark.parametrize(
    "tool,payload,operation",
    [
        ("add_virtual_table_record", {"values": {}}, "add"),
        (
            "update_virtual_table_record",
            {"update": {"values": {}, "expected_revision": 4}},
            "update",
        ),
        ("upsert_virtual_table_record", {"record": {"values": {}}}, "upsert"),
    ],
)
async def test_generic_floor_uses_live_member_context_and_scoped_point_service(
    tool: str, payload: dict[str, object], operation: str
) -> None:
    from unittest.mock import patch
    from uuid import uuid4

    from app.agents.deps import AgentDeps
    from app.agents.platform_approval import may_schedule_agent_work

    deps = AgentDeps(run_id=uuid4(), organization_id=uuid4(), run_person=uuid4())
    manager = MagicMock()
    db = manager.__aenter__.return_value
    ctx = MagicMock()
    service = MagicMock(record_may_schedule_agent_work=AsyncMock(return_value=True))
    with (
        patch("app.agents.platform_approval.get_db_context", return_value=manager),
        patch(
            "app.agents.platform_approval.member_context", new=AsyncMock(return_value=ctx)
        ) as member,
        patch("app.agents.platform_approval.TaskService", return_value=service) as factory,
    ):
        assert await may_schedule_agent_work(
            tool, deps, {**payload, "table_id": str(uuid4()), "record_id": str(uuid4())}
        )
    member.assert_awaited_once_with(
        db, organization_id=deps.organization_id, user_id=deps.run_person
    )
    factory.assert_called_once_with(db)
    assert service.record_may_schedule_agent_work.await_args.kwargs["operation"] == operation


@pytest.mark.anyio
@pytest.mark.security
async def test_conditional_floor_fails_closed_without_current_identity() -> None:
    from unittest.mock import patch
    from uuid import uuid4

    from app.agents.deps import AgentDeps
    from app.agents.platform_approval import may_schedule_agent_work

    deps = AgentDeps(run_id=uuid4())
    assert await may_schedule_agent_work("add_virtual_table_record", deps, {})
    assert await may_schedule_agent_work("future_write", deps, {})
    deps.organization_id, deps.run_person = uuid4(), uuid4()
    manager = MagicMock()
    with (
        patch("app.agents.platform_approval.get_db_context", return_value=manager),
        patch("app.agents.platform_approval.member_context", new=AsyncMock(return_value=None)),
        patch("app.agents.platform_approval.TaskService") as factory,
    ):
        assert await may_schedule_agent_work(
            "add_virtual_table_record", deps, {"table_id": str(uuid4()), "values": {}}
        )
    factory.assert_not_called()


@pytest.mark.anyio
@pytest.mark.security
async def test_fresh_task_execution_floor_blocks_routine_standing_consent() -> None:
    from uuid import uuid4

    from pydantic_ai import ApprovalRequired

    from app.agents.approval import ApprovalPending
    from app.agents.capabilities.approval import ApprovalGate
    from app.agents.deps import AgentDeps
    from app.agents.mcp import CONDITIONAL_EXECUTION, PLATFORM_TOOL
    from app.agents.routine_actions import RoutineToolDecision

    ctx = MagicMock(
        deps=AgentDeps(run_id=uuid4(), request_approval=AsyncMock(return_value=ApprovalPending()))
    )
    definition = ToolDefinition(
        name="create_task",
        metadata={PLATFORM_TOOL: True, CONDITIONAL_EXECUTION: "create_task", NEEDS_APPROVAL: False},
    )
    gate = ApprovalGate(
        routine_policy=AsyncMock(return_value=RoutineToolDecision(consented_by=uuid4()))
    )
    execute = AsyncMock()
    with pytest.raises(ApprovalRequired):
        await gate.wrap_tool_execute(
            ctx,
            call=MagicMock(tool_call_id="task-1"),
            tool_def=definition,
            args={"task": {"title": "Agent task", "assignee_agent_id": str(uuid4())}},
            handler=execute,
        )
    execute.assert_not_awaited()
    assert ctx.deps.request_approval.await_args.args[0].always_asks is True


@pytest.mark.anyio
@pytest.mark.security
@pytest.mark.parametrize("missing", ["record", "revision", "both"])
async def test_update_preflight_without_record_identity_or_revision_never_releases_a_call(
    missing: str,
) -> None:
    from unittest.mock import patch
    from uuid import uuid4

    from app.services.tasks import TaskService

    service = TaskService(MagicMock())
    service.tables = MagicMock(describe_table=AsyncMock(return_value=MagicMock(can_edit=True)))
    with (
        patch("app.services.tasks.task_repo.for_table", new=AsyncMock(return_value=MagicMock())),
        patch("app.services.tasks.task_repo.record", new=AsyncMock()) as read,
    ):
        assert await service.record_may_schedule_agent_work(
            MagicMock(),
            uuid4(),
            {},
            operation="update",
            record_id=None if missing in {"record", "both"} else uuid4(),
            expected_revision=None if missing in {"revision", "both"} else 1,
        )
    read.assert_not_awaited()
