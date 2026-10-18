"""JIT user + personal org when the console authenticates via minerp IAM."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.db.models.user import User
from app.repositories import user as user_repo
from app.services.organization import OrganizationService

logger = logging.getLogger(__name__)


async def _fetch_iam_profile(bearer_token: str) -> dict[str, Any]:
    base = settings.IAM_AUTH_INTERNAL_BASE_URL.rstrip("/")
    url = f"{base}/api/v1/auth/me"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {bearer_token}"})
    if response.status_code != 200:
        raise AuthenticationError(
            message="IAM profile unavailable",
            details={"status": response.status_code},
        )
    return response.json()


async def resolve_iam_user(
    db: AsyncSession,
    *,
    bearer_token: str,
    payload: dict[str, Any],
) -> User:
    """Load or create the AgenticOS user for an IAM JWT subject."""
    raw_sub = payload.get("sub")
    if raw_sub is None:
        raise AuthenticationError(message="Invalid token payload")
    try:
        user_id = UUID(str(raw_sub))
    except ValueError as exc:
        raise AuthenticationError(message="Invalid token subject") from exc

    existing = await user_repo.get_by_id(db, user_id)
    if existing is not None:
        if not existing.is_active:
            raise AuthenticationError(message="User account is disabled")
        return existing

    profile = await _fetch_iam_profile(bearer_token)
    email = str(profile.get("email") or "").strip().lower()
    if not email:
        raise AuthenticationError(message="IAM profile missing email")

    by_email = await user_repo.get_by_email(db, email)
    if by_email is not None:
        if by_email.id != user_id:
            logger.warning(
                "iam_user_email_collision",
                extra={"iam_id": str(user_id), "existing_id": str(by_email.id), "email": email},
            )
            raise AuthenticationError(message="IAM account could not be linked")
        return by_email

    full_name = profile.get("full_name")
    user = await user_repo.create(
        db,
        id=user_id,
        email=email,
        hashed_password=None,
        full_name=full_name if isinstance(full_name, str) else None,
        is_app_admin=False,
        oauth_provider="minerp_iam",
        oauth_id=str(user_id),
    )
    org_service = OrganizationService(db)
    await org_service.create_personal_org(user.id, user.email)
    logger.info("iam_user_provisioned", extra={"user_id": str(user.id), "email": email})
    return user
