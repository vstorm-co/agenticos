"""Re-authenticating a chat WebSocket - at the handshake and on every frame.

A socket is authenticated once, at the handshake, and then held open for its
whole life. Nothing re-checked the credential after that, so a session revoked
while the socket was open - an impersonation ended (#1044), an account
suspended, a signed-out administrator behind an impersonation - went on being
served turn after turn until the client hung up (#1437).

:func:`authenticate_socket_token` is that single check, shared by the handshake
dependency (`get_current_user_ws`) and the per-frame re-validation the session
runs (`AgentSession`), so an open socket is never more permissive than a fresh
connection with the same token: whatever would refuse a new handshake refuses
the next frame.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.security import verify_token
from app.services.impersonation import ImpersonationService
from app.services.user import UserService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.models.user import User


async def authenticate_socket_token(
    db: AsyncSession, token: str, *, allow_expired: bool = False
) -> User:
    """The user a chat socket's access token still resolves to, or a refusal.

    Much of the validation `get_current_user` runs on every HTTP request, so the
    socket is not more permissive than a request bearing the same token: an ended
    impersonation (its `sid` row deactivated, its administrator suspended or
    demoted) and a suspended target account each refuse the token here as they do
    there. Calling :meth:`ImpersonationService.verify` also refreshes the
    request's audit impersonator, so a re-check on the receive loop keeps a turn
    started afterwards attributed to whoever is really acting.

    `allow_expired` is set only by the per-frame re-check on an already-open
    socket. That socket was authenticated when its token was valid and then held
    open past the access token's 30-minute lifetime, so it is not torn down for
    routine token aging - which would cancel a turn a still-signed-in person is
    running (#1437) - and revocation is judged from the impersonation row and the
    account's `is_active` instead. Expiry that *is* a revocation is still caught:
    an impersonation's window is its row's `expires_at`, which `verify` enforces
    regardless. The handshake leaves it False, so a socket cannot be *opened*
    with an already-expired token.

    The returned user is still bound to `db`; the caller detaches it (the
    handshake does, so it can outlive the connection; the per-frame check
    discards it).

    Raises:
        AuthenticationError: The token is invalid (or, unless `allow_expired`,
            expired), is not an access token, carries no subject, names an
            impersonation that has ended, or resolves to a user who is unknown or
            suspended.
    """
    payload = verify_token(token, verify_exp=not allow_expired)
    if payload is None:
        raise AuthenticationError(message="Invalid or expired token")

    if payload.get("type") != "access":
        raise AuthenticationError(message="Invalid token type")

    user_id = payload.get("sub")
    if user_id is None:
        raise AuthenticationError(message="Invalid token payload")

    await ImpersonationService(db).verify(payload=payload, token=token, subject=user_id)

    try:
        user = await UserService(db).get_by_id(UUID(user_id))
    except NotFoundError:
        raise AuthenticationError(message="User not found") from None

    if not user.is_active:
        raise AuthenticationError(message="User account is disabled")

    return user
