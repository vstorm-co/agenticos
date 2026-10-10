"""Live change events, end to end against a real database (#2061).

A write through the public API publishes what it changed; a console socket hears
it only when the subscriber could read the row. Both halves are joins between a
request, a membership and the rows' visibility, so they run against Postgres -
with Redis replaced by an in-memory bus, the one thing here that is transport.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.clients.redis import RedisClient
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.core.security import create_access_token
from app.db.models.agent import Agent
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel, ResourceGrant, Visibility
from app.db.models.user import User
from app.main import app
from app.schemas.api_key import ApiKeyCreate
from app.schemas.change_event import ChangeEvent
from app.services import change_feed
from app.services.api_key import ApiKeyService

pytestmark = pytest.mark.anyio


class _PubSub:
    def __init__(self, bus: _Bus) -> None:
        self.bus = bus
        self.send, self.receive = anyio.create_memory_object_stream[str](16)
        self.channel = ""
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.channel = channel
        self.bus.subscribers.setdefault(channel, []).append(self)
        self.bus.listening.set()

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "subscribe", "data": 1}
        async for data in self.receive:
            yield {"type": "message", "data": data}

    async def end(self) -> None:
        """What Redis does to a subscription when its connection goes away."""
        await self.send.aclose()

    async def aclose(self) -> None:
        self.bus.subscribers[self.channel].remove(self)
        self.closed = True


class _Bus:
    """Redis pub/sub, in memory: what was published, and who is listening."""

    def __init__(self) -> None:
        self.published: list[ChangeEvent] = []
        self.subscribers: dict[str, list[_PubSub]] = {}
        self.pubsubs: list[_PubSub] = []
        self.listening = anyio.Event()

    async def publish(self, channel: str, data: str) -> None:
        event = ChangeEvent.model_validate_json(data)
        assert channel == f"changes:{event.organization_id}"
        self.published.append(event)
        for pubsub in self.subscribers.get(channel, []):
            await pubsub.send.send(data)

    def pubsub(self, *, ignore_subscribe_messages: bool) -> _PubSub:
        assert ignore_subscribe_messages
        pubsub = _PubSub(self)
        self.pubsubs.append(pubsub)
        return pubsub


class _Socket:
    """The accepted console socket: what it was sent, and how it was closed."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed: tuple[int, str] | None = None
        self.heard = anyio.Event()
        self._send, self._receive = anyio.create_memory_object_stream[dict[str, Any]](4)

    async def receive(self) -> dict[str, Any]:
        return await self._receive.receive()

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))
        self.heard.set()

    async def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)

    async def frame(self, message: dict[str, Any]) -> None:
        await self._send.send(message)


@pytest.fixture
def bus() -> AsyncIterator[_Bus]:
    bus = _Bus()
    redis = MagicMock(spec=RedisClient)
    redis.raw = bus
    change_feed.configure(redis)
    yield bus
    change_feed.configure(None)


@pytest.fixture
async def http(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_redis] = lambda: MagicMock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def _person(db: AsyncSession, name: str | None = None) -> User:
    user = User(
        email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True, full_name=name
    )
    db.add(user)
    await db.flush()
    return user


async def _organization(db: AsyncSession, owner: User) -> Organization:
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"))
    await db.flush()
    return organization


async def _join(db: AsyncSession, organization: Organization, role: str) -> User:
    person = await _person(db)
    db.add(OrganizationMember(organization_id=organization.id, user_id=person.id, role=role))
    await db.flush()
    return person


async def _key(db: AsyncSession, organization: Organization, owner: User) -> str:
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
    created = await ApiKeyService(db).create(
        ctx, ApiKeyCreate(name="script", scopes=[Perm.AGENTS_VIEW, Perm.AGENTS_EDIT])
    )
    return created.key


async def _agent(
    db: AsyncSession, organization: Organization, owner: User, visibility: str
) -> Agent:
    agent = Agent(
        organization_id=organization.id,
        owner_user_id=owner.id,
        name="Refunds",
        slug=f"refunds-{uuid.uuid4().hex[:8]}",
        visibility=visibility,
        draft_spec={"name": "Refunds", "instructions": "Answer refund questions."},
    )
    db.add(agent)
    await db.flush()
    return agent


def _event(organization: Organization, actor: User, **overrides: Any) -> ChangeEvent:
    values: dict[str, Any] = {
        "organization_id": organization.id,
        "resource": "agent",
        "id": None,
        "action": "updated",
        "surface": "mcp",
        "actor_user_id": actor.id,
        "actor_name": "Ada",
    }
    values.update(overrides)
    return ChangeEvent(**values)


def _ctx(organization: Organization, user: User, role: str) -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=organization.id, role=role)


class TestPublishing:
    async def test_a_key_s_writes_publish_what_they_changed_and_who_made_them(
        self, db: AsyncSession, http: AsyncClient, bus: _Bus
    ) -> None:
        owner = await _person(db, "Ada Lovelace")
        organization = await _organization(db, owner)
        headers = {"Authorization": f"Bearer {await _key(db, organization, owner)}"}
        base = f"{settings.API_V1_STR}/agents"

        created = await http.post(
            base, headers=headers, json={"spec": {"name": "Refunds", "instructions": "Be kind."}}
        )
        agent_id = created.json()["id"]
        await http.get(f"{base}/{agent_id}", headers=headers)
        await http.put(
            f"{base}/{agent_id}/draft",
            headers=headers,
            json={"spec": {"name": "Refunds", "instructions": "Be brief."}},
        )
        await http.delete(f"{base}/{agent_id}", headers=headers)

        assert [(event.action, str(event.id)) for event in bus.published] == [
            ("created", agent_id),
            ("updated", agent_id),
            ("deleted", agent_id),
        ]
        first = bus.published[0]
        assert first.resource == "agent"
        assert first.surface == "api_key"
        assert first.actor_user_id == owner.id
        assert first.actor_name == "Ada Lovelace"
        assert first.organization_id == organization.id

    async def test_a_refused_write_publishes_nothing(
        self, db: AsyncSession, http: AsyncClient, bus: _Bus
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        viewer = await _join(db, organization, OrgRoleName.VIEWER)
        token = create_access_token(str(viewer.id))

        refused = await http.post(
            f"{settings.API_V1_STR}/agents",
            headers={"Authorization": f"Bearer {token}", "X-Organization-Id": str(organization.id)},
            json={"spec": {"name": "Refunds", "instructions": "Be kind."}},
        )

        assert refused.status_code == 403
        assert bus.published == []

    async def test_a_console_session_is_attributed_to_the_console_and_named_by_email(
        self, db: AsyncSession, http: AsyncClient, bus: _Bus
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        token = create_access_token(str(owner.id))

        await http.patch(
            f"{settings.API_V1_STR}/orgs/{organization.id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Acme Ltd"},
        )

        [event] = bus.published
        assert (event.resource, event.id, event.action) == (
            "organization",
            organization.id,
            "updated",
        )
        assert (event.surface, event.actor_name) == ("console", owner.email)


class TestVisibility:
    @pytest.mark.security
    async def test_a_viewer_hears_nothing_about_an_agent_they_cannot_read(
        self, db: AsyncSession
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        viewer = await _join(db, organization, OrgRoleName.VIEWER)
        private = await _agent(db, organization, owner, Visibility.PRIVATE)
        shared = await _agent(db, organization, owner, Visibility.ORG)
        ctx = _ctx(organization, viewer, OrgRoleName.VIEWER)

        hidden = _event(organization, owner, id=private.id)
        seen = _event(organization, owner, id=shared.id)

        assert not await change_feed.visible(db, ctx, hidden)
        assert await change_feed.visible(db, ctx, seen)

    async def test_a_grant_on_the_row_lets_the_viewer_hear_it(self, db: AsyncSession) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        viewer = await _join(db, organization, OrgRoleName.VIEWER)
        private = await _agent(db, organization, owner, Visibility.PRIVATE)
        db.add(
            ResourceGrant(
                organization_id=organization.id,
                resource_type="agent",
                resource_id=private.id,
                subject_user_id=viewer.id,
                level=GrantLevel.READ,
            )
        )
        await db.flush()

        assert await change_feed.visible(
            db,
            _ctx(organization, viewer, OrgRoleName.VIEWER),
            _event(organization, owner, id=private.id),
        )

    @pytest.mark.security
    async def test_a_deletion_reaches_only_a_role_that_sees_every_row(
        self, db: AsyncSession
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        viewer = await _join(db, organization, OrgRoleName.VIEWER)
        gone = _event(organization, owner, id=uuid.uuid4(), action="deleted")
        unnamed = _event(organization, owner, action="created")

        assert await change_feed.visible(db, _ctx(organization, owner, OrgRoleName.OWNER), gone)
        assert not await change_feed.visible(
            db, _ctx(organization, viewer, OrgRoleName.VIEWER), gone
        )
        assert not await change_feed.visible(
            db, _ctx(organization, viewer, OrgRoleName.VIEWER), unnamed
        )

    async def test_a_row_that_no_longer_exists_is_not_announced(self, db: AsyncSession) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        viewer = await _join(db, organization, OrgRoleName.VIEWER)
        ctx = _ctx(organization, viewer, OrgRoleName.VIEWER)

        for resource in ("agent", "skill", "context", "knowledge_base", "artifact"):
            event = _event(organization, owner, resource=resource, id=uuid.uuid4())
            assert not await change_feed.visible(db, ctx, event)

    @pytest.mark.security
    async def test_invitations_reach_only_whoever_manages_members(self, db: AsyncSession) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        member = await _join(db, organization, OrgRoleName.MEMBER)
        invited = _event(organization, owner, resource="invitation", action="created")
        joined = _event(organization, owner, resource="member", id=member.id)

        assert await change_feed.visible(db, _ctx(organization, owner, OrgRoleName.OWNER), invited)
        assert not await change_feed.visible(
            db, _ctx(organization, member, OrgRoleName.MEMBER), invited
        )
        assert await change_feed.visible(db, _ctx(organization, member, OrgRoleName.MEMBER), joined)

    @pytest.mark.security
    async def test_another_organization_s_change_reaches_nobody_here(
        self, db: AsyncSession
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        elsewhere = await _organization(db, await _person(db))
        foreign = _event(elsewhere, owner, resource="organization", id=elsewhere.id)

        assert not await change_feed.visible(
            db, _ctx(organization, owner, OrgRoleName.OWNER), foreign
        )


async def _stream(socket: _Socket, organization: Organization, token: str) -> None:
    await change_feed.stream_changes(socket, organization_id=organization.id, auth_token=token)


async def _settled(event: anyio.Event) -> None:
    """Wait for the stream to act: each event is a database read on its own session,
    which a scheduler cannot tell from waiting."""
    with anyio.fail_after(5):
        await event.wait()


class TestStream:
    async def test_a_subscriber_hears_what_it_may_read_until_it_disconnects(
        self, db: AsyncSession, bus: _Bus
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        viewer = await _join(db, organization, OrgRoleName.VIEWER)
        private = await _agent(db, organization, owner, Visibility.PRIVATE)
        shared = await _agent(db, organization, owner, Visibility.ORG)
        await db.commit()
        socket = _Socket()

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_stream, socket, organization, create_access_token(str(viewer.id)))
            await _settled(bus.listening)
            await change_feed.publish(_event(organization, owner, id=private.id))
            await change_feed.publish(_event(organization, owner, id=shared.id))
            await _settled(socket.heard)
            await socket.frame({"type": "websocket.receive", "text": "ignored"})
            await socket.frame({"type": "websocket.disconnect"})

        assert [frame["id"] for frame in socket.sent] == [str(shared.id)]
        assert socket.sent[0]["surface"] == "mcp"
        assert bus.pubsubs[0].closed

    @pytest.mark.security
    async def test_a_subscriber_removed_from_the_organization_is_cut_off(
        self, db: AsyncSession, bus: _Bus
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        await db.commit()
        outsider = await _person(db)
        await db.commit()
        socket = _Socket()

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_stream, socket, organization, create_access_token(str(outsider.id)))
            await _settled(bus.listening)
            await change_feed.publish(_event(organization, owner, resource="member", id=owner.id))

        assert socket.sent == []
        assert socket.closed == (4403, "Access revoked")
        assert bus.pubsubs[0].closed

    @pytest.mark.security
    async def test_a_revoked_credential_is_cut_off(self, db: AsyncSession, bus: _Bus) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        await db.commit()
        socket = _Socket()

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_stream, socket, organization, "not-a-token")
            await _settled(bus.listening)
            await change_feed.publish(_event(organization, owner, resource="member", id=owner.id))

        assert socket.closed == (4403, "Access revoked")

    async def test_a_key_holder_is_judged_by_the_key(self, db: AsyncSession, bus: _Bus) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        key = await _key(db, organization, owner)
        await db.commit()
        socket = _Socket()

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_stream, socket, organization, key)
            await _settled(bus.listening)
            await change_feed.publish(_event(organization, owner, resource="member", id=owner.id))
            await _settled(socket.heard)
            await socket.frame({"type": "websocket.disconnect"})

        assert [frame["resource"] for frame in socket.sent] == ["member"]

    async def test_a_subscription_redis_ends_closes_the_socket_for_a_retry(
        self, db: AsyncSession, bus: _Bus
    ) -> None:
        owner = await _person(db)
        organization = await _organization(db, owner)
        await db.commit()
        socket = _Socket()

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_stream, socket, organization, create_access_token(str(owner.id)))
            await _settled(bus.listening)
            await bus.pubsubs[0].end()

        assert socket.closed == (1011, "Live updates were interrupted")
        assert bus.pubsubs[0].closed
