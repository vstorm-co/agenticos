"""Isolation and refusal contracts for internal workflow-agent conversation identities."""

import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.services.workflow_execution import agent_conversations as chats
from app.services.workflow_execution.context import DispatchContext

pytestmark = pytest.mark.anyio


def current() -> DispatchContext:
    org = uuid4()
    return DispatchContext(
        organization_id=org,
        workflow_id=uuid4(),
        workflow_run_id=uuid4(),
        node_run_id=uuid4(),
        node_instance_id=uuid4(),
        attempt_no=1,
        auth=AuthContext(user_id=uuid4(), organization_id=org, role="owner"),
        resumed_agent_run_id=None,
    )


def test_keys_are_scoped_and_never_trust_a_payload_conversation():
    ctx = current()
    agent, version, token = uuid4(), uuid4(), uuid4()
    plain = chats.conversation_key(ctx, agent, version)
    assert (
        chats.conversation_key(
            dataclasses.replace(ctx, run_input={"conversation_id": str(token)}), agent, version
        )
        == plain
    )
    assert (
        chats.conversation_key(dataclasses.replace(ctx, node_run_id=uuid4()), agent, version)
        != plain
    )
    for kind in ("test_chat_key", "source_conversation_id"):
        session = dataclasses.replace(ctx, **{kind: token})
        key = chats.conversation_key(session, agent, version)
        assert key != token
        assert (
            chats.conversation_key(
                dataclasses.replace(session, node_run_id=uuid4()), agent, version
            )
            == key
        )
        for change in (
            {"workflow_id": uuid4()},
            {"node_instance_id": uuid4()},
            {"organization_id": uuid4()},
            {"nested": True},
            {kind: uuid4()},
            {
                "auth": AuthContext(
                    user_id=uuid4(), organization_id=ctx.organization_id, role="owner"
                )
            },
        ):
            assert (
                chats.conversation_key(dataclasses.replace(session, **change), agent, version)
                != key
            )
        assert chats.conversation_key(session, uuid4(), version) != key
        assert chats.conversation_key(session, agent, uuid4()) != key
    assert chats.conversation_key(
        dataclasses.replace(ctx, test_chat_key=token), agent, version
    ) != chats.conversation_key(
        dataclasses.replace(ctx, source_conversation_id=token), agent, version
    )


async def test_opens_an_unlisted_thread_and_reads_its_own_history(monkeypatch):
    ctx = current()
    opened = uuid4()
    ensure = AsyncMock(return_value=SimpleNamespace(id=opened))
    history = AsyncMock(return_value=[])
    monkeypatch.setattr(chats.conversation_repo, "ensure_workflow_conversation", ensure)
    monkeypatch.setattr(
        chats, "ConversationService", lambda db: SimpleNamespace(model_history=history)
    )
    result = await chats.for_agent_step(
        MagicMock(spec=AsyncSession), ctx, agent_id=uuid4(), version_id=uuid4()
    )
    assert result.id == opened and result.history == []
    assert ensure.await_args.kwargs["workflow_id"] == ctx.workflow_id
    assert ensure.await_args.kwargs["source_conversation_id"] is None
    assert ensure.await_args.kwargs["project_id"] is None


async def test_inherits_only_the_authorized_source_project(monkeypatch):
    ctx = dataclasses.replace(current(), source_conversation_id=uuid4())
    project, opened = uuid4(), uuid4()
    monkeypatch.setattr(
        chats.conversation_repo,
        "get_conversation_by_id",
        AsyncMock(
            return_value=SimpleNamespace(organization_id=ctx.organization_id, project_id=project)
        ),
    )
    ensure = AsyncMock(return_value=SimpleNamespace(id=opened))
    monkeypatch.setattr(chats.conversation_repo, "ensure_workflow_conversation", ensure)
    monkeypatch.setattr(
        chats,
        "ConversationService",
        lambda db: SimpleNamespace(model_history=AsyncMock(return_value=[])),
    )
    await chats.for_agent_step(
        MagicMock(spec=AsyncSession), ctx, agent_id=uuid4(), version_id=uuid4()
    )
    assert ensure.await_args.kwargs["project_id"] == project
    assert ensure.await_args.kwargs["source_conversation_id"] == ctx.source_conversation_id


@pytest.mark.parametrize("source", [None, SimpleNamespace(organization_id=uuid4())])
async def test_a_missing_or_other_tenant_source_is_refused(monkeypatch, source):
    monkeypatch.setattr(
        chats.conversation_repo, "get_conversation_by_id", AsyncMock(return_value=source)
    )
    with pytest.raises(NotFoundError):
        await chats.for_agent_step(
            MagicMock(spec=AsyncSession),
            dataclasses.replace(current(), source_conversation_id=uuid4()),
            agent_id=uuid4(),
            version_id=uuid4(),
        )


async def test_missing_workflow_or_an_id_collision_is_refused(monkeypatch):
    db = MagicMock(spec=AsyncSession)
    with pytest.raises(NotFoundError):
        await chats.for_agent_step(
            db,
            dataclasses.replace(current(), workflow_id=None),
            agent_id=uuid4(),
            version_id=uuid4(),
        )
    monkeypatch.setattr(
        chats.conversation_repo, "ensure_workflow_conversation", AsyncMock(return_value=None)
    )
    with pytest.raises(NotFoundError):
        await chats.for_agent_step(db, current(), agent_id=uuid4(), version_id=uuid4())


async def test_internal_threads_are_not_readable_or_editable_as_project_chats(monkeypatch):
    from app.db.models.conversation import Conversation
    from app.services.conversation import ConversationService

    service = ConversationService(MagicMock(spec=AsyncSession))
    allowed = AsyncMock(return_value=True)
    monkeypatch.setattr(service, "_project_allows", allowed)
    thread = Conversation(
        id=uuid4(), organization_id=uuid4(), origin="workflow", project_id=uuid4()
    )
    assert not await service._may_read(thread, uuid4())
    assert not await service._may_write(thread, uuid4(), turn=True)
    allowed.assert_not_awaited()


def test_only_test_chat_graphs_interpret_the_opaque_session_token():
    from app.db.models.workflow_run import WorkflowRun
    from app.services.workflow_execution.dispatcher import _test_chat_key
    from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph

    token = uuid4()
    entry = NodeInstance(
        id=uuid4(),
        definition_id="trigger.chat",
        definition_version=1,
        config={},
        layout=NodePosition(x=0, y=0),
    )
    graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))
    run = WorkflowRun(mode="test", input={"conversation_id": str(token)})
    assert _test_chat_key(run, graph) == token
    run.mode = "real"
    assert _test_chat_key(run, graph) is None
    run.mode = "test"
    for invalid in (None, 42, "invalid"):
        run.input = {"conversation_id": invalid}
        assert _test_chat_key(run, graph) is None
    run.input = {"conversation_id": str(token)}
    plain = entry.model_copy(update={"definition_id": "trigger.manual"})
    assert _test_chat_key(run, graph.model_copy(update={"nodes": (plain,)})) is None
    assert _test_chat_key(run, graph.model_copy(update={"entry_node_id": uuid4()})) is None
