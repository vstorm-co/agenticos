"""Minerp IAM JWT bridge (B31)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import jwt
import pytest

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.iam_auth import iam_token_allowed, is_iam_access_payload, verify_iam_token
from app.services.access_auth import resolve_user_from_access_token

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _iam_payload(*, sub: str | None = None, permissions: list[str] | None = None) -> dict:
    return {
        "sub": sub or str(uuid4()),
        "type": "access",
        "permissions": permissions or ["agentra.console:read"],
        "tenant_ids": [],
        "has_global_scope": False,
    }


def _mint_iam_token(payload: dict, *, secret: str | None = None) -> str:
    key = secret or settings.SECRET_KEY
    return jwt.encode(payload, key, algorithm=settings.ALGORITHM)


class TestIamAuthHelpers:
    def test_detects_iam_payload_shape(self) -> None:
        assert is_iam_access_payload(_iam_payload()) is True
        assert is_iam_access_payload({"sub": "x", "type": "access"}) is False

    def test_console_permission_gate(self) -> None:
        assert iam_token_allowed(_iam_payload(permissions=["agentra.console:read"])) is True
        assert iam_token_allowed(_iam_payload(permissions=["other:read"])) is False
        assert iam_token_allowed({**_iam_payload(permissions=[]), "has_global_scope": True}) is True

    async def test_verify_disabled_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "IAM_AUTH_ENABLED", False)
        token = _mint_iam_token(_iam_payload())
        assert verify_iam_token(token) is None


class TestResolveUserFromAccessTokenIam:
    async def test_iam_token_provisions_via_resolve_iam_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "IAM_AUTH_ENABLED", True)
        user = MagicMock()
        user.is_active = True
        user_id = uuid4()
        payload = _iam_payload(sub=str(user_id))
        token = _mint_iam_token(payload)

        db = MagicMock()
        with (
            patch("app.services.access_auth.verify_token", return_value=None),
            patch("app.services.access_auth.verify_iam_token", return_value=payload),
            patch("app.services.access_auth.resolve_iam_user", AsyncMock(return_value=user)) as resolve,
        ):
            resolved = await resolve_user_from_access_token(db, token)

        assert resolved is user
        resolve.assert_awaited_once()

    async def test_iam_token_without_permission_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "IAM_AUTH_ENABLED", True)
        token = _mint_iam_token(_iam_payload(permissions=["nope"]))

        bad = _iam_payload(permissions=["nope"])
        with (
            patch("app.services.access_auth.verify_token", return_value=None),
            patch("app.services.access_auth.verify_iam_token", return_value=bad),
            pytest.raises(AuthenticationError, match="Missing Agentra console permission"),
        ):
            await resolve_user_from_access_token(MagicMock(), token)
