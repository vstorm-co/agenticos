"""Signing a phone in by scanning a code the console shows (#2097).

The console, signed in, asks for a pairing code and draws it as a QR. The phone
scans it and redeems the code for a session of its own. The code is single-use
and lives a minute, like the OAuth exchange code (`oauth_exchange.py`), and it
holds no tokens: the session is created when the code is *redeemed*, under the
phone's own address and user agent, so a code nobody scanned leaves no session
behind in the person's list, and the list names the phone rather than the
laptop that showed the QR.

What the code carries is who asked and at which credential version. A password
changed between showing the QR and scanning it - which revokes every session -
refuses the code too, rather than signing the phone in past the change.
"""

import json
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.exceptions import AuthenticationError
from app.core.security import create_access_token, create_refresh_token
from app.db.models.user import User

if TYPE_CHECKING:
    from app.clients.redis import RedisClient
    from app.services.session import SessionService
    from app.services.user import UserService

_KEY = "auth:pairing:{code}"
PAIRING_TTL_SECONDS = 60


@dataclass(frozen=True)
class PairingCode:
    code: str
    expires_in: int


@dataclass(frozen=True)
class PairedSession:
    access_token: str
    refresh_token: str


class DevicePairingService:
    """Mint a pairing code for the signed-in person, and redeem one into a session."""

    def __init__(self, redis: RedisClient, users: UserService, sessions: SessionService) -> None:
        self.redis = redis
        self.users = users
        self.sessions = sessions

    async def issue(self, user: User) -> PairingCode:
        """A fresh code that signs one device in as `user`, once, within the minute."""
        code = secrets.token_urlsafe(32)
        grant = json.dumps({"user_id": str(user.id), "credential_version": user.credential_version})
        await self.redis.set(_KEY.format(code=code), grant, ttl=PAIRING_TTL_SECONDS)
        return PairingCode(code=code, expires_in=PAIRING_TTL_SECONDS)

    async def preview(self, code: str) -> User:
        """Identify the target account without consuming its code or creating a session."""
        raw = await self.redis.get(_KEY.format(code=code))
        if raw is None:
            raise AuthenticationError(message="This pairing code has expired. Show a new one.")
        return await self._user(raw)

    async def _user(self, raw: str) -> User:
        grant = json.loads(raw)
        user = await self.users.get_by_id(UUID(grant["user_id"]))
        if not user.is_active or user.credential_version != grant["credential_version"]:
            raise AuthenticationError(message="This pairing code has expired. Show a new one.")
        return user

    async def redeem(
        self, code: str, *, ip_address: str | None, user_agent: str | None
    ) -> PairedSession:
        """Consume a code and open the device's session.

        Raises:
            AuthenticationError: the code is unknown, spent or expired; or the
                account was deactivated, or its password changed, since the code
                was shown. The four are one refusal: a scanner learns nothing
                about which it hit.
        """
        raw = await self.redis.getdel(_KEY.format(code=code))
        if raw is None:
            raise AuthenticationError(message="This pairing code has expired. Show a new one.")
        user = await self._user(raw)
        refresh_token = create_refresh_token(
            subject=str(user.id), credential_version=user.credential_version
        )
        session = await self.sessions.create_session(
            user_id=user.id,
            refresh_token=refresh_token,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        access_token = create_access_token(subject=str(user.id), sid=str(session.id))
        return PairedSession(access_token=access_token, refresh_token=refresh_token)
