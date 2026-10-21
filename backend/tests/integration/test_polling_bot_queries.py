"""What the stream keeper reads, on a real Postgres.

Every API worker asks which bots should stream; it asked for the full rows,
sealed tokens included, every ten seconds - most of production's statements on
an idle day. It now reads ids, and the full rows only for the bots it claimed.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_bot import ChannelBot
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import channel_bot as channel_bot_repo

pytestmark = pytest.mark.anyio


async def _organization(db: AsyncSession) -> Organization:
    founder = User(
        id=uuid.uuid4(), email=f"f-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x"
    )
    db.add(founder)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(org)
    await db.flush()
    return org


async def _bot(
    db: AsyncSession, org: Organization, platform: str, **overrides: object
) -> ChannelBot:
    bot = ChannelBot(
        id=uuid.uuid4(),
        organization_id=org.id,
        platform=platform,
        name=f"{platform}-{uuid.uuid4().hex[:4]}",
        token_encrypted="sealed-elsewhere",
        **overrides,
    )
    db.add(bot)
    await db.flush()
    return bot


async def test_the_ids_are_the_active_polling_bots_and_nothing_else(db: AsyncSession) -> None:
    org = await _organization(db)
    telegram = await _bot(db, org, "telegram")
    slack = await _bot(db, org, "slack")
    await _bot(db, org, "telegram", is_active=False)
    await _bot(db, org, "telegram", webhook_mode=True)
    await _bot(db, org, "teams")

    ids = await channel_bot_repo.get_active_polling_bot_ids(db, "telegram", "mattermost", "slack")

    assert set(ids) >= {telegram.id, slack.id}
    rows = await channel_bot_repo.get_active_polling_bots(db, "telegram", "slack")
    assert {row.id for row in rows} >= {telegram.id, slack.id}
    assert not {row.id for row in rows} - set(ids)


async def test_the_full_rows_are_read_only_for_the_bots_asked_for(db: AsyncSession) -> None:
    org = await _organization(db)
    claimed = await _bot(db, org, "telegram")
    await _bot(db, org, "telegram")
    paused = await _bot(db, org, "telegram", is_active=False)

    rows = await channel_bot_repo.get_active_polling_bots(
        db, "telegram", ids=[claimed.id, paused.id]
    )

    assert [row.id for row in rows] == [claimed.id]
