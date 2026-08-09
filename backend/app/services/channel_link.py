"""Connecting a chat account to the person behind it.

A run started from a channel belongs to somebody: the budget it spends, the
resources it may read and the audit entry it writes are all theirs. A message
arrives carrying a platform user id and nothing else, so the connection has to be
made from the side that is already authenticated - somebody signed into the
dashboard mints a code, then types it at the bot.

Until this existed, `/link` could not succeed on any platform. Nothing in the
repository ever wrote `channel_identities.link_code`, so every code was "invalid
or expired", every identity kept `user_id = NULL`, and `ChannelAgentRouter`
refused every message on every channel with "Link your account first" (#10).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_link_code import ChannelLinkCode
from app.repositories import channel_identity_repo, channel_link_code_repo

# No `0`/`O`, `1`/`I`/`l`: the code is read off one screen and typed into
# another, sometimes from a phone, and a character somebody has to disambiguate
# is a support conversation.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8

CODE_TTL = timedelta(minutes=10)
"""How long a code lives.

It is a bearer credential: whoever types it becomes the account, as far as every
channel is concerned. Ten minutes is long enough to switch windows and short
enough that a code left in a chat log is not a way in.
"""


def new_code() -> str:
    """One code, from an alphabet a person can read aloud."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))


class ChannelLinkService:
    """Mint a code for a signed-in user, and spend one on behalf of a chat."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def mint(self, user_id: UUID) -> ChannelLinkCode:
        """Issue a code, replacing any the user already has outstanding.

        One at a time, deliberately: somebody who asks again because the first
        code scrolled off the screen must not leave a live credential behind
        them.
        """
        await channel_link_code_repo.delete_for_user(self.db, user_id=user_id)
        return await channel_link_code_repo.create(
            self.db,
            user_id=user_id,
            code=new_code(),
            expires_at=datetime.now(UTC) + CODE_TTL,
        )

    async def redeem(
        self,
        code: str,
        *,
        platform: str,
        platform_user_id: str,
        platform_username: str | None = None,
        platform_display_name: str | None = None,
    ) -> bool:
        """Spend a code, attaching this chat account to the user who minted it.

        Returns whether it was spent. A wrong code and an expired one answer the
        same way, because the difference is not something the person typing can
        act on differently - and both are told to generate a new one.

        Every code the user holds is dropped afterwards, not just this one: the
        code is spent, and a second outstanding code for an account that is now
        linked is a credential with nothing left to do.
        """
        found = await channel_link_code_repo.get_valid(
            self.db, code=code.strip().upper(), now=datetime.now(UTC)
        )
        if found is None:
            return False

        identity = await channel_identity_repo.get_by_platform_user(
            self.db, platform=platform, platform_user_id=platform_user_id
        )
        if identity is None:
            await channel_identity_repo.create(
                self.db,
                platform=platform,
                platform_user_id=platform_user_id,
                platform_username=platform_username,
                platform_display_name=platform_display_name,
                user_id=found.user_id,
            )
        else:
            await channel_identity_repo.update(
                self.db, db_identity=identity, update_data={"user_id": found.user_id}
            )

        await channel_link_code_repo.delete_for_user(self.db, user_id=found.user_id)
        return True
