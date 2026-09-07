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


async def authenticate_socket_token(db: AsyncSession, token: str) -> User:
    """The user a chat socket's access token still resolves to, or a refusal.

    The same validation `get_current_user` runs on every HTTP request, so the
    socket is no more permissive than a request bearing the same token: an
    expired token, an ended impersonation (its `sid` row deactivated, its
    administrator suspended or demoted), and a suspended target account each
    refuse the token here as they do there. Calling :meth:`ImpersonationService.verify`
    also refreshes the request's audit impersonator, so a re-check on the
    receive loop keeps a turn started afterwards attributed to whoever is really
    acting.

    The returned user is still bound to `db`; the caller detaches it (the
    handshake does, so it can outlive the connection; the per-frame check
    discards it).

    Raises:
        AuthenticationError: The token is invalid or expired, is not an access
            token, carries no subject, names an impersonation that has ended, or
            resolves to a user who is unknown or suspended.
    """
    payload = verify_token(token)
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
