"""Shared access-token → User resolution (native AgenticOS + minerp IAM)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.core.config import settings
from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.iam_auth import (
    iam_token_allowed,
    is_iam_access_payload,
    verify_iam_token,
)
from app.core.security import verify_token
from app.services.iam_user_provision import resolve_iam_user
from app.services.impersonation import ImpersonationService
from app.services.session import SessionService
from app.services.user import UserService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.models.user import User


async def resolve_user_from_access_token(
    db: AsyncSession,
    token: str,
    *,
    allow_expired: bool = False,
) -> User:
    payload = verify_token(token, verify_exp=not allow_expired)
    iam = False
    if payload is None:
        payload = verify_iam_token(token, verify_exp=not allow_expired)
        iam = payload is not None
    elif is_iam_access_payload(payload):
        iam = True

    if payload is None:
        raise AuthenticationError(message="Invalid or expired token")

    if payload.get("type") != "access":
        raise AuthenticationError(message="Invalid token type")

    user_id = payload.get("sub")
    if user_id is None:
        raise AuthenticationError(message="Invalid token payload")

    if iam:
        if not iam_token_allowed(payload):
            raise AuthenticationError(message="Missing Agentra console permission")
        user = await resolve_iam_user(db, bearer_token=token, payload=payload)
        if settings.MINERP_TENANT_ORG_SYNC_ENABLED:
            from app.services.minerp_tenant_sync import sync_tenant_orgs_from_iam_payload

            await sync_tenant_orgs_from_iam_payload(db, user_id=user.id, payload=payload)
        return user

    await ImpersonationService(db).verify(payload=payload, token=token, subject=str(user_id))
    await SessionService(db).verify_access_session(payload=payload, subject=str(user_id))

    try:
        user = await UserService(db).get_by_id(UUID(str(user_id)))
    except NotFoundError as exc:
        raise AuthenticationError(message="User not found") from exc
    if not user.is_active:
        raise AuthenticationError(message="User account is disabled")
    return user
