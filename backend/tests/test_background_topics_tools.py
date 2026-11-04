"""The model receives task controls only through an authorized published source."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext
from app.agents.capabilities.background_tasks import _build
from app.agents.capabilities.background_tasks._toolset import build_background_tasks_toolset
from app.agents.deps import AgentDeps
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext
from app.schemas.local_target import LocalTarget

pytestmark = pytest.mark.anyio
PERSON, ORG, THREAD, RUN = uuid4(), uuid4(), uuid4(), uuid4()


def context() -> RunContext[AgentDeps]:
    return RunContext(
        deps=AgentDeps(
            organization_id=ORG,
            user_id=str(PERSON),
            run_person=PERSON,
            run_id=RUN,
            conversation_id=THREAD,
        ),
        model=TestModel(),
        usage=RunUsage(),
        tool_call_id="call",
        max_retries=1,
    )


@asynccontextmanager
async def database():
    yield MagicMock()


def test_builder_uses_only_a_resolved_local_target() -> None:
    local = LocalTarget(folder="/approved", mode="full_access", device_id=uuid4())
    for value in [None, "untrusted", local]:
        built = _build(
            CapabilityBuildContext(
                binding=CapabilityBinding(capability_id="background_tasks"),
                config=None,
                resources={"background_tasks.local": value},
            )
        )
        assert built.local == (local if value is local else None)
        assert set(built.get_toolset().tools) == {
            "start_background_task",
            "list_background_tasks",
            "stop_background_task",
        }
        assert "do not poll" in built.get_instructions()(context())
        child = context()
        child.deps.conversation_task_id = uuid4()
        assert "already executing" in built.get_instructions()(child)


@pytest.mark.parametrize("missing", ["run", "conversation", "tool_call", "impersonated"])
async def test_start_refuses_unidentified_or_impersonated_calls(missing: str) -> None:
    ctx = context()
    if missing == "tool_call":
        ctx.tool_call_id = None
    elif missing == "impersonated":
        ctx.deps.impersonated = True
    else:
        setattr(ctx.deps, f"{missing}_id", None)
    result = (
        await build_background_tasks_toolset(local=None)
        .tools["start_background_task"]
        .function(ctx, title="Bug", prompt="Investigate")
    )
    assert "signed-in" in result


async def test_tools_use_current_authority_and_the_sources_own_conversation() -> None:
    auth = AuthContext(user_id=PERSON, organization_id=ORG, role="member")
    task = MagicMock(source_conversation_id=THREAD)
    task.model_dump_json.return_value = '{"status":"queued"}'
    service = MagicMock()
    service.start = AsyncMock(return_value=task)
    service.list_for_member = AsyncMock(return_value=[task])
    service.get = AsyncMock(return_value=task)
    service.stop = AsyncMock(return_value=task)
    tools = build_background_tasks_toolset(local=None).tools
    ctx = context()
    with (
        patch("app.agents.capabilities.background_tasks._toolset.get_db_context", database),
        patch(
            "app.agents.capabilities.background_tasks._toolset.acting_member",
            new=AsyncMock(return_value=auth),
        ) as member,
        patch(
            "app.agents.capabilities.background_tasks._toolset.ConversationTaskService",
            return_value=service,
        ),
    ):
        assert "queued" in await tools["start_background_task"].function(
            ctx, title="Bug", prompt="Investigate"
        )
        assert service.start.call_args.kwargs["source_run_id"] == RUN
        assert service.start.call_args.kwargs["tool_call_id"] == "call"
        assert "queued" in await tools["list_background_tasks"].function(ctx)
        assert service.list_for_member.call_args.kwargs["conversation_id"] == THREAD
        assert "queued" in await tools["stop_background_task"].function(ctx, task_id=uuid4())
        task.source_conversation_id = uuid4()
        assert "not started" in await tools["stop_background_task"].function(ctx, task_id=uuid4())
        for name, kwargs in [
            ("start_background_task", {"title": "Bug", "prompt": "Investigate"}),
            ("list_background_tasks", {}),
            ("stop_background_task", {"task_id": uuid4()}),
        ]:
            method = {
                "start_background_task": "start",
                "list_background_tasks": "list_for_member",
                "stop_background_task": "get",
            }[name]
            getattr(service, method).side_effect = AuthorizationError(message="Removed")
            assert "Refused" in await tools[name].function(ctx, **kwargs)
            getattr(service, method).side_effect = None
            member.return_value = None
            assert "active organization member" in await tools[name].function(ctx, **kwargs)
            member.return_value = auth
        ctx.deps.run_person = None
        assert "active organization member" in await tools["start_background_task"].function(
            ctx, title="Bug", prompt="Investigate"
        )
        ctx.deps.conversation_id = None
        assert "No source" in await tools["list_background_tasks"].function(ctx)


@pytest.mark.parametrize("refusal", ["owner", "missing_version", "disabled"])
async def test_source_ownership_and_the_published_switch_are_checked(refusal: str) -> None:
    from types import SimpleNamespace

    from app.core.exceptions import NotFoundError
    from app.schemas.conversation_task import StartConversationTask
    from app.services.conversation_tasks import ConversationTaskService

    auth = AuthContext(user_id=PERSON, organization_id=ORG, role="member")
    source = SimpleNamespace(
        id=RUN,
        user_id=PERSON,
        conversation_id=THREAD,
        agent_id=uuid4(),
        agent_version_id=uuid4(),
        surface="web",
        parent_run_id=None,
        is_test=False,
    )
    version = (
        None
        if refusal == "missing_version"
        else SimpleNamespace(
            spec={
                "name": "Assistant",
                "capabilities": [{"id": "background_tasks", "enabled": False}],
            }
        )
    )
    service = ConversationTaskService(MagicMock())
    with (
        patch(
            "app.services.conversation_tasks.run_repo.get_run", new=AsyncMock(return_value=source)
        ),
        patch(
            "app.services.conversation_tasks.task_repo.for_run", new=AsyncMock(return_value=None)
        ),
        patch.object(service, "_topic", new=AsyncMock()),
        patch.object(
            service.conversations,
            "get_conversation",
            new=AsyncMock(
                return_value=SimpleNamespace(user_id=uuid4() if refusal == "owner" else PERSON)
            ),
        ),
        patch(
            "app.services.conversation_tasks.agent_repo.get_version",
            new=AsyncMock(return_value=version),
        ),
        pytest.raises((AuthorizationError, NotFoundError)),
    ):
        await service.start(
            auth,
            source_run_id=RUN,
            tool_call_id="call",
            request=StartConversationTask(title="Task", prompt="Brief"),
        )
