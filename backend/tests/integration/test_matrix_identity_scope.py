"""Real account links and erasure never cross Matrix homeserver boundaries."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.db.models.background_job import BackgroundJob
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_link_request import ChannelLinkRequest
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import channel_identity_repo, channel_link_request_repo, personal_data_repo
from app.schemas.channel_bot import ChannelIdentityRead, ChannelLinkRequestRead
from app.services.channel_link import ChannelLinkService
from app.services.channels.base import IncomingMessage
from app.services.channels.router import ChannelMessageRouter

pytestmark = pytest.mark.anyio
SERVER_A = "https://a.example.org"
SERVER_B = "https://b.example.org"
NATIVE_USER = "@ada:example.org"


async def test_links_backfill_and_erasure_are_homeserver_scoped(db: AsyncSession) -> None:
    users = [User(email=f"{uuid4()}@example.org", is_active=True) for _ in range(2)]
    db.add_all(users)
    await db.flush()
    org = Organization(name="Matrix", slug=f"matrix-{uuid4()}", created_by_user_id=users[0].id)
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=users[0].id, role="member"))
    bots = [
        ChannelBot(
            organization_id=org.id,
            platform="matrix",
            name="Matrix",
            token_encrypted="unused",
            api_base_url=server,
            access_policy={"mode": "open"},
        )
        for server in (SERVER_A, SERVER_B)
    ]
    db.add_all(bots)
    await db.flush()
    service = ChannelLinkService(db)
    messages = [
        IncomingMessage(
            platform="matrix",
            bot_id=str(bot.id),
            platform_user_id=NATIVE_USER,
            platform_chat_id="!room%3Adomain",
            chat_type="private",
            text="/link",
            raw={"server_url": server},
        )
        for bot, server in zip(bots, (SERVER_A, SERVER_B), strict=True)
    ]
    links = [await service.request(message) for message in messages]
    assert links[0] != links[1]
    for link, server, user in zip(links, (SERVER_A, SERVER_B), users, strict=True):
        token = link.rsplit("/", 1)[-1]
        pending = await service.pending(token)
        assert pending is not None
        assert ChannelLinkRequestRead.model_validate(pending).server_url == server
        assert await service.confirm(token, user.id) is not None
        assert await service.confirm(token, user.id) is None
    identities = [
        await channel_identity_repo.get_by_platform_user(
            db, "matrix", NATIVE_USER, server_url=server
        )
        for server in (SERVER_A, SERVER_B)
    ]
    assert all(identity is not None for identity in identities)
    first, second = identities
    assert first is not None and second is not None
    assert first.id != second.id and first.user_id == users[0].id and second.user_id == users[1].id
    assert ChannelIdentityRead.model_validate(first).server_url == SERVER_A
    for server, expected in ((SERVER_A, {NATIVE_USER}), (SERVER_B, set())):
        assert (
            await channel_identity_repo.linked_active_platform_user_ids(
                db,
                platform="matrix",
                platform_user_ids=[NATIVE_USER],
                organization_id=org.id,
                server_url=server,
            )
            == expected
        )
    # Reissuing A's link must not invalidate B's pending consent.
    await service.request(messages[1])
    await service.request(messages[0])
    await service.request(messages[0])
    assert (
        await channel_link_request_repo.get_for_identity(
            db, platform="matrix", platform_user_id=NATIVE_USER, server_url=SERVER_B
        )
        is not None
    )
    # A stale stream cannot mint a link or pass admission after the bot changes server.
    bots[0].api_base_url = SERVER_B
    await db.flush()
    with pytest.raises(AuthorizationError, match="homeserver"):
        await service.request(messages[0])
    with pytest.raises(AuthorizationError, match="homeserver"):
        ChannelMessageRouter()._check_access(messages[0], bots[0])
    # Erasing A removes only A's queued native messages, even when B claims the same ID.
    jobs = [
        BackgroundJob(
            kind="process-channel-message",
            pool="agent",
            max_attempts=1,
            organization_id=org.id,
            payload={"platform": "matrix", "platform_user_id": NATIVE_USER, "server_url": server},
        )
        for server in (SERVER_A, SERVER_B)
    ]
    db.add_all(jobs)
    await db.flush()
    assert await personal_data_repo.purge_identities_of(db, users[0].id) == 1
    assert list(await db.scalars(select(BackgroundJob.id))) == [jobs[1].id]
    assert (
        await channel_identity_repo.get_by_platform_user(
            db, "matrix", NATIVE_USER, server_url=SERVER_B
        )
        is second
    )


async def test_unscoped_preview_links_cannot_claim_an_account(db: AsyncSession) -> None:
    legacy = ChannelLinkRequest(
        token="legacy-matrix",
        platform="matrix",
        platform_user_id=NATIVE_USER,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    db.add(legacy)
    await db.flush()
    service = ChannelLinkService(db)
    assert await service.pending(legacy.token) is None
    assert await service.confirm(legacy.token, uuid4()) is None
