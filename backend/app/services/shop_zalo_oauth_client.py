"""HTTP client for Zalo OA OAuth v4 (Shop AI)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.exceptions import BadRequestError, ExternalServiceError

logger = logging.getLogger(__name__)

ZALO_OA_PERMISSION_URL = "https://oauth.zaloapp.com/v4/oa/permission"
ZALO_OA_ACCESS_TOKEN_URL = "https://oauth.zaloapp.com/v4/oa/access_token"


class ShopZaloOAuthClient:
    def __init__(
        self,
        *,
        app_id: str | None = None,
        app_secret: str | None = None,
        redirect_uri: str | None = None,
    ) -> None:
        self._app_id = (app_id or settings.ZALO_OA_APP_ID).strip()
        self._app_secret = (app_secret or settings.ZALO_OA_APP_SECRET).strip()
        self._redirect_uri = (redirect_uri or settings.ZALO_OA_OAUTH_REDIRECT_URI).strip()

    def _require_configured(self) -> None:
        if not self._app_id or not self._app_secret or not self._redirect_uri:
            raise BadRequestError(
                message="Zalo OAuth is not configured",
                details={
                    "hint": "Set ZALO_OA_APP_ID, ZALO_OA_APP_SECRET, ZALO_OA_OAUTH_REDIRECT_URI",
                },
            )

    def authorize_url(self, *, state: str, code_challenge: str) -> str:
        self._require_configured()
        redirect = quote(self._redirect_uri, safe="")
        return (
            f"{ZALO_OA_PERMISSION_URL}?app_id={self._app_id}"
            f"&redirect_uri={redirect}"
            f"&code_challenge={code_challenge}"
            f"&state={quote(state, safe='')}"
        )

    async def exchange_code(self, *, code: str, code_verifier: str) -> dict[str, Any]:
        self._require_configured()
        return await self._token_request(
            {
                "app_id": self._app_id,
                "code": code,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            }
        )

    async def refresh_access_token(self, *, refresh_token: str) -> dict[str, Any]:
        self._require_configured()
        return await self._token_request(
            {
                "app_id": self._app_id,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        )

    async def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        headers = {
            "secret_key": self._app_secret,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(ZALO_OA_ACCESS_TOKEN_URL, data=form, headers=headers)
        except httpx.HTTPError as exc:
            raise ExternalServiceError(
                message="Zalo OAuth token request failed",
                details={"error": str(exc)[:200]},
            ) from exc
        if resp.status_code >= 400:
            logger.warning("Zalo OAuth token error %s: %s", resp.status_code, resp.text[:300])
            raise ExternalServiceError(
                message="Zalo OAuth token exchange failed",
                details={"status": resp.status_code, "body": resp.text[:200]},
            )
        body = resp.json()
        if not isinstance(body, dict):
            raise ExternalServiceError(message="Invalid Zalo OAuth response", details={})
        if body.get("error") or body.get("error_name"):
            raise ExternalServiceError(
                message="Zalo OAuth rejected request",
                details={"error": str(body.get("error") or body.get("error_name"))},
            )
        access = str(body.get("access_token") or "").strip()
        refresh = str(body.get("refresh_token") or "").strip()
        if not access or not refresh:
            raise ExternalServiceError(
                message="Zalo OAuth response missing tokens",
                details={"keys": sorted(body.keys())},
            )
        expires_in = int(body.get("expires_in") or 3600)
        return {
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": expires_in,
        }
