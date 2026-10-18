"""Minerp IAM (`services/auth`) JWT helpers for AgenticOS extension mode."""

from __future__ import annotations

from typing import Any

import jwt

from app.core.config import settings


def iam_jwt_secret() -> str:
    return (settings.IAM_JWT_SECRET_KEY or settings.SECRET_KEY).strip()


def is_iam_access_payload(payload: dict[str, Any]) -> bool:
    """Auth access tokens carry RBAC claims AgenticOS-native tokens do not."""
    if payload.get("type") != "access":
        return False
    return "permissions" in payload or "tenant_ids" in payload or "has_global_scope" in payload


def verify_iam_token(token: str, *, verify_exp: bool = True) -> dict[str, Any] | None:
    if not settings.IAM_AUTH_ENABLED:
        return None
    try:
        return jwt.decode(
            token,
            iam_jwt_secret(),
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": verify_exp},
        )
    except jwt.PyJWTError:
        return None


def iam_token_allowed(payload: dict[str, Any]) -> bool:
    required = settings.IAM_CONSOLE_PERMISSION.strip()
    if not required:
        return True
    perms = payload.get("permissions") or []
    if not isinstance(perms, list):
        return False
    if payload.get("has_global_scope") is True:
        return True
    return required in perms or "system:admin" in perms
