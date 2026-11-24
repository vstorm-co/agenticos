"""The room endpoints refuse everyone who is not a current participant, over HTTP.

The service tests call the services with a hand-built context. These go through
the real routes, dependencies and database, so a missing guard on a route cannot
hide behind a service that happens to refuse the same input.
"""

from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.permissions import AuthContext
from app.db.models.conversation import Message
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.room_message_reaction import RoomMessageReaction
from app.db.models.room_participant import RoomParticipant
from app.db.models.room_submission import RoomSubmission
from app.db.models.user import User
from app.main import app
from app.schemas.room_participant import RoomParticipantRef
from app.services.room_participant import RoomParticipantService
from tests.integration.test_room_submissions import Room, seed_multiplayer

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_EMOJI = {"emoji": "👍"}


@dataclass
class Scene:
    room: Room
    insider: User
    outsider: User
    message: Message
    agent_id: UUID
    contexts: dict[str, tuple[User, AuthContext]]


async def _member(db: AsyncSession, organization_id: UUID, role: str = "viewer") -> User:
    user = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid4(), organization_id=organization_id, user_id=user.id, role=role)
    )
    await db.flush()
    return user


@pytest.fixture
async def scene(db: AsyncSession) -> AsyncGenerator[Scene]:
    room, second, insider = await seed_multiplayer(db)
    organization_id = room.ctx.organization_id
    outsider = await _member(db, organization_id)
    removed = await _member(db, organization_id)
    roster = RoomParticipantService(db)
    await roster.add(room.ctx, room.conversation.id, RoomParticipantRef(kind="user", id=removed.id))
    await roster.remove(
        room.ctx, room.conversation.id, RoomParticipantRef(kind="user", id=removed.id)
    )

    stranger = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(stranger)
    await db.flush()
    stranger_org = Organization(
        id=uuid4(), name="Elsewhere", slug=f"else-{uuid4().hex}", created_by_user_id=stranger.id
    )
    db.add(stranger_org)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid4(), organization_id=stranger_org.id, user_id=stranger.id, role="owner"
        )
    )
    message = Message(conversation_id=room.conversation.id, role="assistant", content="Hello")
    db.add(message)
    await db.flush()

    def context(user: User, org: UUID, role: str, **extra: Any) -> tuple[User, AuthContext]:
        return user, AuthContext(user_id=user.id, organization_id=org, role=role, **extra)

    contexts = {
        "outsider": context(outsider, organization_id, "viewer"),
        "removed participant": context(removed, organization_id, "viewer"),
        "another organization": context(stranger, stranger_org.id, "owner"),
        "key without scope": context(
            room.user, organization_id, "owner", api_key_id=uuid4(), key_scopes=frozenset()
        ),
    }
    yield Scene(room, insider, outsider, message, second.id, contexts)


@pytest.fixture
async def call(db: AsyncSession) -> AsyncGenerator[Callable[..., Any]]:
    """Send one request as a chosen user and context through the real app."""

    async def session() -> AsyncGenerator[AsyncSession]:
        yield db

    async def send(user: User, ctx: AuthContext, method: str, path: str, body: Any = None) -> Any:
        organization = await db.get(Organization, ctx.organization_id)
        app.dependency_overrides[deps.get_db_session] = session
        app.dependency_overrides[deps.get_current_user] = lambda: user
        app.dependency_overrides[deps.get_active_organization] = lambda: organization
        app.dependency_overrides[deps.get_auth_context] = lambda: ctx
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.request(method, f"/api/v1/conversations/{path}", json=body)
        finally:
            app.dependency_overrides.clear()

    yield send


def _routes(scene: Scene) -> list[tuple[str, str, Any]]:
    room = scene.room.conversation.id
    message = scene.message.id
    return [
        ("GET", f"{room}/participants", None),
        ("POST", f"{room}/participants", {"kind": "user", "id": str(scene.outsider.id)}),
        ("DELETE", f"{room}/participants/user/{scene.insider.id}", None),
        ("PATCH", f"{room}/participants/agent/{scene.agent_id}", {"auto_reply": True}),
        ("GET", f"{room}/room-mentionables", None),
        ("POST", f"{room}/room-messages", {"client_message_id": "http-1", "content": "Hi"}),
        ("GET", f"{room}/room-requests", None),
        ("GET", f"{room}/room-threads/{message}", None),
        ("POST", f"{room}/room-threads/{message}/close", None),
        ("POST", f"{room}/room-threads/{message}/reopen", None),
        ("POST", f"{room}/room-threads/{message}/archive", None),
        ("POST", f"{room}/room-threads/{message}/unarchive", None),
        ("PUT", f"{room}/room-threads/{message}/follow", None),
        ("DELETE", f"{room}/room-threads/{message}/follow", None),
        ("POST", f"{room}/room-threads/{message}/read", {"through_message_id": str(message)}),
        ("PUT", f"{room}/messages/{message}/reactions", _EMOJI),
        ("DELETE", f"{room}/messages/{message}/reactions", _EMOJI),
    ]


async def _room_state(db: AsyncSession, scene: Scene) -> list[int | None]:
    room = scene.room.conversation.id
    counts: list[int | None] = []
    for model, column in (
        (RoomParticipant, RoomParticipant.conversation_id),
        (Message, Message.conversation_id),
        (RoomSubmission, RoomSubmission.conversation_id),
    ):
        counts.append(
            await db.scalar(select(func.count()).select_from(model).where(column == room))
        )
    counts.append(await db.scalar(select(func.count()).select_from(RoomMessageReaction)))
    return counts


@pytest.mark.parametrize(
    "identity", ["outsider", "removed participant", "another organization", "key without scope"]
)
async def test_every_room_endpoint_refuses_a_caller_who_is_not_a_current_participant(
    db: AsyncSession, scene: Scene, call: Callable[..., Any], identity: str
):
    user, ctx = scene.contexts[identity]
    before = await _room_state(db, scene)
    # A bare 404 from an unknown route has no `error` body, so the code also
    # proves each path names a real route that refused on purpose.
    expected = (
        (403, "AUTHORIZATION_ERROR") if identity == "key without scope" else (404, "NOT_FOUND")
    )

    refused = {}
    for method, path, body in _routes(scene):
        response = await call(user, ctx, method, path, body)
        refused[f"{method} {path}"] = (response.status_code, response.json()["error"]["code"])

    assert set(refused.values()) <= {expected}, refused
    assert await _room_state(db, scene) == before


async def test_the_same_requests_succeed_for_a_current_participant(
    db: AsyncSession, scene: Scene, call: Callable[..., Any]
):
    """The refusals above are about the caller: a participant is not refused."""
    ctx = replace(scene.room.ctx)
    room = scene.room.conversation.id
    listed = await call(scene.room.user, ctx, "GET", f"{room}/participants")
    assert listed.status_code == 200, listed.text
    reacted = await call(
        scene.room.user, ctx, "PUT", f"{room}/messages/{scene.message.id}/reactions", _EMOJI
    )
    assert reacted.status_code == 200, reacted.text


async def test_a_reaction_is_refused_once_the_reacting_participant_is_removed(
    db: AsyncSession, scene: Scene, call: Callable[..., Any]
):
    room = scene.room.conversation.id
    path = f"{room}/messages/{scene.message.id}/reactions"
    person = AuthContext(
        user_id=scene.insider.id,
        organization_id=scene.room.ctx.organization_id,
        role="viewer",
    )

    reacted = await call(scene.insider, person, "PUT", path, _EMOJI)
    assert reacted.status_code == 200, reacted.text
    assert await db.scalar(select(func.count()).select_from(RoomMessageReaction)) == 1

    await RoomParticipantService(db).remove(
        scene.room.ctx, room, RoomParticipantRef(kind="user", id=scene.insider.id)
    )

    for method in ("PUT", "DELETE"):
        refused = await call(scene.insider, person, method, path, {"emoji": "🎉"})
        assert refused.status_code == 404, (method, refused.text)
    taken_back = await call(scene.insider, person, "DELETE", path, _EMOJI)
    assert taken_back.status_code == 404, taken_back.text
    stored = (await db.scalars(select(RoomMessageReaction))).all()
    assert [(row.user_id, row.emoji) for row in stored] == [(scene.insider.id, "👍")]
