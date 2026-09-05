"""Session service (PostgreSQL async)."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.db.models.session import Session
from app.repositories import session_repo
from app.schemas.session import SessionListResponse, SessionRead


def hash_token(token: str) -> str:
    """The fingerprint a session row holds for its credential; never the credential."""
    return hashlib.sha256(token.encode()).hexdigest()


def _parse_user_agent(user_agent: str | None) -> tuple[str | None, str | None]:
    if not user_agent:
        return None, None

    user_agent_lower = user_agent.lower()

    if "mobile" in user_agent_lower or "android" in user_agent_lower:
        device_type = "mobile"
    elif "tablet" in user_agent_lower or "ipad" in user_agent_lower:
        device_type = "tablet"
    else:
        device_type = "desktop"

    if "chrome" in user_agent_lower:
        device_name = "Chrome"
    elif "firefox" in user_agent_lower:
        device_name = "Firefox"
    elif "safari" in user_agent_lower:
        device_name = "Safari"
    elif "edge" in user_agent_lower:
        device_name = "Edge"
    else:
        device_name = "Unknown Browser"

    return device_name, device_type


class SessionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_session(
        self,
        user_id: UUID,
        refresh_token: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Session:
        device_name, device_type = _parse_user_agent(user_agent)
        expires_at = datetime.now(UTC) + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)

        return await session_repo.create(
            self.db,
            user_id=user_id,
            refresh_token_hash=hash_token(refresh_token),
            expires_at=expires_at,
            device_name=device_name,
            device_type=device_type,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def get_user_sessions(self, user_id: UUID) -> list[Session]:
        return await session_repo.get_user_sessions(self.db, user_id, open_only=True)

    async def count_user_sessions(self, user_id: UUID, *, now: datetime | None = None) -> int:
        return await session_repo.count_user_sessions(self.db, user_id, open_only=True, now=now)

    async def validate_refresh_token(self, refresh_token: str) -> Session | None:
        """The session a refresh token belongs to, or None for one that cannot refresh.

        An impersonation row is found by the hash of its *access* token, and a
        refresh minted from it would be a plain token as the target - no `act`,
        no `sid`, a fresh week-long session - which launders the administrator
        out of every request that follows and makes the impersonation unendable
        again (#1044). So an impersonation is not a refresh token, whoever holds
        it: its window is the access token's own, and nothing extends it.
        """
        token_hash = hash_token(refresh_token)
        session = await session_repo.get_by_refresh_token_hash(self.db, token_hash)

        if (
            session
            and session.impersonator_user_id is None
            and session.expires_at > datetime.now(UTC)
        ):
            await session_repo.update_last_used(self.db, session.id)
            return session

        return None

    async def open_impersonation(
        self,
        *,
        session_id: UUID,
        target_id: UUID,
        impersonator_id: UUID,
        access_token: str,
        expires_at: datetime,
        ip_address: str | None,
        user_agent: str | None,
    ) -> Session:
        """The row an administrator's access to somebody else's account is.

        Its id is the caller's, because the token that names it in `sid` has to be
        minted before the row exists and the row has to hold that token's hash:
        one of the two is decided first, and an id is the cheaper one to decide.
        The device columns are the administrator's browser, which is where the
        session actually is.
        """
        device_name, device_type = _parse_user_agent(user_agent)
        return await session_repo.create(
            self.db,
            session_id=session_id,
            user_id=target_id,
            refresh_token_hash=hash_token(access_token),
            expires_at=expires_at,
            device_name=device_name,
            device_type=device_type,
            ip_address=ip_address,
            user_agent=user_agent,
            impersonator_user_id=impersonator_id,
        )

    async def logout_session(self, session_id: UUID, user_id: UUID) -> Session:
        session = await session_repo.get_by_id(self.db, session_id)
        if not session or session.user_id != user_id:
            raise NotFoundError(message="Session not found")

        await session_repo.deactivate(self.db, session_id)
        return session

    async def logout_all_sessions(self, user_id: UUID) -> int:
        return await session_repo.deactivate_all_user_sessions(self.db, user_id)

    async def logout_by_refresh_token(self, refresh_token: str) -> Session | None:
        token_hash = hash_token(refresh_token)
        return await session_repo.deactivate_by_refresh_token_hash(self.db, token_hash)

    async def list_sessions(
        self,
        user_id: UUID,
        *,
        skip: int = 0,
        limit: int = 10,
    ) -> SessionListResponse:
        """One page of the user's active sessions, most recently used first.

        `total` is counted separately rather than taken from the page, because
        the caller pages on it: revoking the last session on a page has to leave
        the client able to work out that the page is gone.
        """
        # One cutoff for both statements. A session lapsing between them would
        # otherwise be in the page and outside the total, which breaks the
        # invariant the caller pages on without anybody writing a row.
        now = datetime.now(UTC)
        sessions = await session_repo.get_user_sessions(
            self.db, user_id, open_only=True, now=now, skip=skip, limit=limit
        )
        total = await self.count_user_sessions(user_id, now=now)
        return SessionListResponse(
            items=[
                SessionRead(
                    id=s.id,
                    device_name=s.device_name,
                    device_type=s.device_type,
                    ip_address=s.ip_address,
                    is_current=False,
                    created_at=s.created_at,
                    last_used_at=s.last_used_at,
                )
                for s in sessions
            ],
            total=total,
        )
