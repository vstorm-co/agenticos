"""Where a Teams bot can post, against a real database (#1985).

The record is an upsert, the name survives an activity that carries none, and
only a team channel or group chat of the organization's is ever a trigger's
target - all three are Postgres's answer, not a mock's.
"""

import uuid

import pytest

from app.db.models.channel_bot import ChannelBot
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import teams_conversation_repo

pytestmark = pytest.mark.anyio

SERVICE = "https://smba.trafficmanager.net/emea/"


async def _bot(db, *, active: bool = True) -> ChannelBot:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@acme.com", hashed_password="x")
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(), name="Acme", slug=uuid.uuid4().hex[:12], created_by_user_id=user.id
    )
    db.add(org)
    await db.flush()
    bot = ChannelBot(
        organization_id=org.id,
        platform="teams",
        name="Support",
        token_encrypted="sealed",
        secret_key_version=1,
        is_active=active,
        webhook_mode=True,
    )
    db.add(bot)
    await db.flush()
    return bot


async def _record(db, bot: ChannelBot, key: str, kind: str, name: str | None, service=SERVICE):
    await teams_conversation_repo.record(
        db,
        organization_id=bot.organization_id,
        bot_id=bot.id,
        key=key,
        conversation_id=f"conv-{key}",
        service_url=service,
        tenant_id="t",
        conversation_type=kind,
        name=name,
    )


async def test_a_second_activity_moves_the_service_and_keeps_the_name(db) -> None:
    bot = await _bot(db)
    await _record(db, bot, "k1", "channel", "General")
    await _record(db, bot, "k1", "channel", None, service="https://smba.trafficmanager.net/amer/")

    row = await teams_conversation_repo.get_by_key(db, "k1")
    assert row is not None
    await db.refresh(row)
    assert row.name == "General"
    assert row.service_url.endswith("/amer/")


@pytest.mark.security
async def test_only_the_organizations_channels_are_targets(db) -> None:
    """A group chat is private to its participants: shared for finding somebody
    to greet, never a place a routine posts into (Codex on #2324)."""
    bot = await _bot(db)
    other = await _bot(db)
    await _record(db, bot, "channel", "channel", "General")
    await _record(db, bot, "group", "groupChat", "Launch")
    await _record(db, bot, "personal", "personal", None)
    await _record(db, other, "elsewhere", "channel", "Theirs")

    shared = await teams_conversation_repo.list_shared(db, organization_id=bot.organization_id)
    assert {row.key for row in shared} == {"channel", "group"}
    postable = await teams_conversation_repo.list_shared(
        db,
        organization_id=bot.organization_id,
        types=teams_conversation_repo.POSTABLE_TYPES,
    )
    assert [row.key for row in postable] == ["channel"]

    personal = await teams_conversation_repo.get_by_key(db, "personal")
    elsewhere = await teams_conversation_repo.get_by_key(db, "elsewhere")
    group = await teams_conversation_repo.get_by_key(db, "group")
    assert personal is not None and elsewhere is not None and group is not None
    org = bot.organization_id
    for refused in (personal, elsewhere, group):
        assert (
            await teams_conversation_repo.get_postable(db, refused.id, organization_id=org) is None
        )
    assert await teams_conversation_repo.get_postable(db, postable[0].id, organization_id=org)


async def test_a_switched_off_bots_conversations_are_not_offered(db) -> None:
    bot = await _bot(db, active=False)
    await _record(db, bot, "quiet", "channel", "General")

    assert await teams_conversation_repo.list_shared(db, organization_id=bot.organization_id) == []
