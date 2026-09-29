"""The workflow-run WebSocket against a real Postgres (#1792).

The socket opens its own sessions, so each test points `get_db_context` at the
test database and replaces only the token check - everything the socket reads
and writes goes through the real services. The run is ended from outside, the
way a worker would, and the socket has to notice it on its own.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import AuthenticationError
from app.core.permissions import AuthContext
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowStatus, WorkflowVersion
from app.db.models.workflow_run import WorkflowRun
from app.services import workflow_run_socket
from app.services.workflow_execution import WorkflowExecutionService, events
from app.services.workflow_run_socket import WorkflowRunSocket
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph

pytestmark = pytest.mark.anyio


class _Socket:
    """What the session needs of a WebSocket: somewhere to send, a way to close."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed: int | None = None
        self.arrived = asyncio.Event()

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)
        self.arrived.set()

    async def close(self, code: int, reason: str) -> None:
        self.closed = code

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [frame for frame in self.sent if frame["type"] == kind]


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    monkeypatch.setattr(workflow_run_socket, "POLL_SECONDS", 0.01)
    with patch("app.worker.tasks.workflow_tasks.run_deployment", new=AsyncMock()):
        yield


@pytest.fixture
def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    made = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def context() -> AsyncIterator[AsyncSession]:
        async with made() as db:
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    with patch.object(workflow_run_socket, "get_db_context", context):
        yield made


async def _tenant(factory) -> tuple[User, Organization, Workflow]:
    async with factory() as db:
        owner = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password="x",
            is_active=True,
        )
        db.add(owner)
        await db.flush()
        org = Organization(
            id=uuid.uuid4(),
            name="Acme",
            slug=f"a-{uuid.uuid4().hex[:8]}",
            created_by_user_id=owner.id,
        )
        db.add(org)
        await db.flush()
        db.add(
            OrganizationMember(
                id=uuid.uuid4(), organization_id=org.id, user_id=owner.id, role="owner"
            )
        )
        entry = NodeInstance(
            id=uuid.uuid4(),
            definition_id="debug.echo",
            definition_version=1,
            config={"message": "hi"},
            layout=NodePosition(x=0, y=0),
        )
        graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry,)).model_dump(mode="json")
        workflow = Workflow(
            id=uuid.uuid4(),
            organization_id=org.id,
            owner_user_id=owner.id,
            slug=f"wf-{uuid.uuid4().hex[:8]}",
            name="Echo",
            status=WorkflowStatus.PUBLISHED.value,
            visibility=Visibility.PRIVATE.value,
            draft_graph=graph,
        )
        db.add(workflow)
        await db.flush()
        version = WorkflowVersion(
            id=uuid.uuid4(), workflow_id=workflow.id, organization_id=org.id, version=1, graph=graph
        )
        db.add(version)
        await db.flush()
        workflow.current_version_id = version.id
        await db.commit()
    return owner, org, workflow


def _session(socket: _Socket, org: Organization) -> WorkflowRunSocket:
    return WorkflowRunSocket(socket, organization_id=org.id, auth_token="token")  # type: ignore[arg-type]


def _signed_in(user: User):
    return patch.object(
        workflow_run_socket, "authenticate_socket_token", new=AsyncMock(return_value=user)
    )


async def _until(socket: _Socket, kind: str, count: int = 1) -> None:
    # Only a guard against a hang: under a loaded parallel suite one poll of a
    # real run's events has taken longer than five seconds.
    async with asyncio.timeout(30):
        while len(socket.of(kind)) < count:
            socket.arrived.clear()
            await socket.arrived.wait()


async def _cancel(factory, owner: User, org: Organization, run_id: uuid.UUID) -> None:
    async with factory() as db:
        await WorkflowExecutionService(db).cancel(
            AuthContext(user_id=owner.id, organization_id=org.id, role="owner"), run_id
        )
        await db.commit()


class TestStartAndFollow:
    async def test_a_started_run_is_announced_streamed_and_closed_when_it_ends(self, factory):
        owner, org, workflow = await _tenant(factory)
        socket = _Socket()
        session = _session(socket, org)
        with _signed_in(owner):
            await session.handle_frame(
                {"type": "start", "workflow_id": str(workflow.id), "input": {"lead": 3}}
            )
            await _until(socket, "run")
            run_id = uuid.UUID(socket.of("run")[0]["run"]["id"])
            await _cancel(factory, owner, org, run_id)
            await _until(socket, "run", 2)
            await session.stop()

        async with factory() as db:
            run = await db.get(WorkflowRun, run_id)
        assert run is not None
        assert (run.triggered_by, run.input, run.reply_conversation_id) == (
            "websocket",
            {"lead": 3},
            None,
        )
        kinds = [frame["event"]["kind"] for frame in socket.of("event")]
        assert kinds[0] == events.EventKind.RUN_STARTED
        assert kinds[-1] == events.EventKind.RUN_CANCELLED
        assert socket.of("run")[-1]["run"]["status"] == "cancelled"

    async def test_a_reconnect_picks_up_after_its_last_cursor(self, factory):
        owner, org, workflow = await _tenant(factory)
        first = _Socket()
        with _signed_in(owner):
            session = _session(first, org)
            await session.handle_frame({"type": "start", "workflow_id": str(workflow.id)})
            await _until(first, "event")
            await session.stop()
            run_id = first.of("run")[0]["run"]["id"]
            cursor = first.of("event")[-1]["cursor"]
            await _cancel(factory, owner, org, uuid.UUID(run_id))

            second = _Socket()
            again = _session(second, org)
            await again.handle_frame({"type": "attach", "run_id": run_id, "after": cursor})
            await _until(second, "run", 2)

        seen = [frame["event"]["kind"] for frame in first.of("event")]
        missed = [frame["event"]["kind"] for frame in second.of("event")]
        assert events.EventKind.RUN_STARTED in seen
        assert events.EventKind.RUN_STARTED not in missed
        assert missed[-1] == events.EventKind.RUN_CANCELLED
        async with factory() as db:
            assert len((await db.execute(select(WorkflowRun))).scalars().all()) == 1

    async def test_a_new_frame_replaces_the_run_being_followed(self, factory):
        owner, org, workflow = await _tenant(factory)
        socket = _Socket()
        session = _session(socket, org)
        with _signed_in(owner):
            await session.handle_frame({"type": "start", "workflow_id": str(workflow.id)})
            await _until(socket, "run")
            following = session._stream
            await session.handle_frame({"type": "start", "workflow_id": str(workflow.id)})
            await _until(socket, "run", 2)
            assert following is not None and following.cancelled()
            await session.stop()
        await session.stop()

    async def test_a_backlog_longer_than_a_page_is_read_again_at_once(self, factory, monkeypatch):
        owner, org, workflow = await _tenant(factory)
        monkeypatch.setattr(workflow_run_socket, "_PAGE", 1)
        socket = _Socket()
        session = _session(socket, org)
        with _signed_in(owner):
            await session.handle_frame({"type": "start", "workflow_id": str(workflow.id)})
            await _until(socket, "run")
            await _cancel(factory, owner, org, uuid.UUID(socket.of("run")[0]["run"]["id"]))
            await _until(socket, "run", 2)
        kinds = [frame["event"]["kind"] for frame in socket.of("event")]
        assert kinds[-1] == events.EventKind.RUN_CANCELLED and len(kinds) >= 2


class TestTheChatsDoor:
    async def test_a_chat_turn_writes_the_message_and_freezes_the_reply_destination(self, factory):
        owner, org, workflow = await _tenant(factory)
        async with factory() as db:
            conversation = Conversation(id=uuid.uuid4(), organization_id=org.id, user_id=owner.id)
            db.add(conversation)
            await db.commit()
        socket = _Socket()
        session = _session(socket, org)
        with _signed_in(owner):
            await session.handle_frame(
                {
                    "type": "start",
                    "workflow_id": str(workflow.id),
                    "conversation_id": str(conversation.id),
                    "message": "Summarise the leads",
                }
            )
            await _until(socket, "run")
            await session.stop()

        run_id = uuid.UUID(socket.of("run")[0]["run"]["id"])
        async with factory() as db:
            run = await db.get(WorkflowRun, run_id)
            messages = (
                (
                    await db.execute(
                        select(Message).where(Message.conversation_id == conversation.id)
                    )
                )
                .scalars()
                .all()
            )
        assert run is not None
        assert (run.triggered_by, run.input, run.reply_conversation_id) == (
            "chat",
            {"prompt": "Summarise the leads"},
            conversation.id,
        )
        assert [(m.role, m.content) for m in messages] == [("user", "Summarise the leads")]

    @pytest.mark.security
    @pytest.mark.parametrize("whose", ["someone-else", "missing", "no-message"])
    async def test_a_reply_destination_that_is_not_the_members_own_is_refused(self, factory, whose):
        owner, org, workflow = await _tenant(factory)
        async with factory() as db:
            other = User(
                id=uuid.uuid4(),
                email=f"{uuid.uuid4().hex}@example.com",
                hashed_password="x",
                is_active=True,
            )
            db.add(other)
            await db.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                organization_id=org.id,
                user_id=other.id if whose == "someone-else" else owner.id,
            )
            db.add(conversation)
            await db.commit()
        frame: dict[str, Any] = {
            "type": "start",
            "workflow_id": str(workflow.id),
            "conversation_id": str(uuid.uuid4() if whose == "missing" else conversation.id),
        }
        if whose != "no-message":
            frame["message"] = "hi"
        socket = _Socket()
        with _signed_in(owner):
            await _session(socket, org).handle_frame(frame)

        assert socket.of("error")[0]["code"] == "NOT_FOUND"
        async with factory() as db:
            assert (await db.execute(select(WorkflowRun))).scalars().all() == []
            assert (await db.execute(select(Message))).scalars().all() == []


class TestRefusals:
    async def test_a_frame_it_does_not_know_is_ignored_without_a_query(self, factory):
        _owner, org, _workflow = await _tenant(factory)
        socket = _Socket()
        check = AsyncMock()
        with patch.object(workflow_run_socket, "authenticate_socket_token", new=check):
            await _session(socket, org).handle_frame({"type": "ping"})
        check.assert_not_awaited()
        assert socket.sent == []

    async def test_a_malformed_frame_is_answered_with_an_error(self, factory):
        owner, org, _workflow = await _tenant(factory)
        socket = _Socket()
        with _signed_in(owner):
            await _session(socket, org).handle_frame({"type": "attach", "run_id": "nope"})
        assert socket.of("error")[0]["code"] == "BAD_FRAME"

    @pytest.mark.security
    async def test_a_run_the_member_cannot_see_is_not_found(self, factory):
        owner, org, workflow = await _tenant(factory)
        socket = _Socket()
        session = _session(socket, org)
        with _signed_in(owner):
            await session.handle_frame({"type": "attach", "run_id": str(uuid.uuid4())})
            await session._stream
        assert socket.of("error")[0]["code"] == "WORKFLOW_RUN_NOT_FOUND"
        assert socket.of("run") == []

    @pytest.mark.security
    async def test_a_revoked_session_closes_the_socket_before_acting(self, factory):
        _owner, org, workflow = await _tenant(factory)
        socket = _Socket()
        with patch.object(
            workflow_run_socket,
            "authenticate_socket_token",
            new=AsyncMock(side_effect=AuthenticationError(message="revoked")),
        ):
            await _session(socket, org).handle_frame(
                {"type": "start", "workflow_id": str(workflow.id)}
            )
        assert socket.closed == 4001
        async with factory() as db:
            assert (await db.execute(select(WorkflowRun))).scalars().all() == []

    @pytest.mark.security
    async def test_a_member_removed_mid_stream_stops_being_served(self, factory):
        owner, org, workflow = await _tenant(factory)
        socket = _Socket()
        session = _session(socket, org)
        with _signed_in(owner):
            await session.handle_frame({"type": "start", "workflow_id": str(workflow.id)})
            await _until(socket, "run")
            async with factory() as db:
                await db.execute(
                    delete(OrganizationMember).where(OrganizationMember.user_id == owner.id)
                )
                await db.commit()
            async with asyncio.timeout(5):
                await session._stream
        assert socket.closed == 4001

    async def test_a_send_to_a_socket_that_went_away_is_dropped(self, factory):
        owner, org, _workflow = await _tenant(factory)

        class _Gone(_Socket):
            async def send_json(self, data: dict[str, Any]) -> None:
                raise RuntimeError("closed")

            async def close(self, code: int, reason: str) -> None:
                raise RuntimeError("closed")

        socket = _Gone()
        with _signed_in(owner):
            await _session(socket, org).handle_frame({"type": "attach", "run_id": "nope"})
        with patch.object(
            workflow_run_socket,
            "authenticate_socket_token",
            new=AsyncMock(side_effect=AuthenticationError(message="revoked")),
        ):
            await _session(socket, org).handle_frame({"type": "start", "workflow_id": "x"})
