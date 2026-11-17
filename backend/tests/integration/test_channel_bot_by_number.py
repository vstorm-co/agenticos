"""Finding the WhatsApp bots that own a number, against real rows (#2076)."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models.channel_bot import ChannelBot
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import channel_bot as channel_bot_repo

pytestmark = pytest.mark.anyio


async def _org(db) -> Organization:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@acme.com", hashed_password="x")
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(), name="Acme", slug=uuid.uuid4().hex[:12], created_by_user_id=user.id
    )
    db.add(org)
    await db.flush()
    return org


async def _bot(
    db,
    org: Organization,
    *,
    account: str | None = "WABA-N",
    number: str | None = "PN-N",
    platform: str = "whatsapp",
    active: bool = True,
) -> ChannelBot:
    bot = ChannelBot(
        organization_id=org.id,
        platform=platform,
        name="Support",
        token_encrypted="sealed",
        secret_key_version=1,
        is_active=active,
        whatsapp_account_id=account,
        whatsapp_phone_number_id=number,
    )
    db.add(bot)
    await db.flush()
    return bot


async def test_active_whatsapp_bots_with_the_pair_are_returned_across_organizations(db) -> None:
    first, second = await _org(db), await _org(db)
    a = await _bot(db, first, account="WABA-1", number="PN-1")
    b = await _bot(db, second, account="WABA-1", number="PN-1")
    c = await _bot(db, first, account="WABA-2", number="PN-2")
    await _bot(db, first, account="WABA-3", number="PN-3")

    found = await channel_bot_repo.get_active_whatsapp_by_numbers(
        db, pairs=[("WABA-1", "PN-1"), ("WABA-2", "PN-2")]
    )

    assert {bot.id for bot in found} == {a.id, b.id, c.id}


async def test_inactive_other_platform_and_half_matching_bots_are_not_returned(db) -> None:
    org = await _org(db)
    await _bot(db, org, account="WABA-4", number="PN-4", active=False)
    await _bot(db, org, account="WABA-4", number="PN-4", platform="slack")
    await _bot(db, org, account="WABA-4", number="PN-other")
    await _bot(db, org, account="WABA-other", number="PN-4")

    assert (
        await channel_bot_repo.get_active_whatsapp_by_numbers(db, pairs=[("WABA-4", "PN-4")]) == []
    )


async def test_no_pairs_is_no_query(db) -> None:
    with patch.object(db, "execute", AsyncMock()) as execute:
        assert await channel_bot_repo.get_active_whatsapp_by_numbers(db, pairs=[]) == []

    execute.assert_not_awaited()
