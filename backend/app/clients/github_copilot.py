"""Copilot account operations with a caller-owned OAuth application identity."""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Literal, Protocol

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai.exceptions import UserError
from pydantic_ai.providers.github_copilot import (
    GitHubCopilotDeviceAuthorization,
    GitHubCopilotOAuthFlow,
)

from app.core.exceptions import BadRequestError

BASE_URL = "https://api.githubcopilot.com"
HEADERS = {"User-Agent": "AgenticOS", "copilot-integration-id": "agenticos"}


def bearer_token(value: str) -> str:
    """Validate header safety without ever echoing an invalid credential."""
    if not value or len(value) > 8192 or not all("!" <= character <= "~" for character in value):
        raise BadRequestError(
            message="Copilot requires a bearer token without whitespace or control characters."
        )
    return value


class CopilotModel(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    id: str = Field(min_length=1, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    supported_endpoints: list[str] = Field(default_factory=list)


class _Models(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    data: list[CopilotModel] = Field(max_length=2048)


class CopilotGrant(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    access_token: str = Field(min_length=8, max_length=8192, repr=False)
    token_type: Literal["bearer"]
    scope: str = ""
    refresh_token: str | None = Field(default=None, repr=False)
    expires_in: int | None = None
    refresh_token_expires_in: int | None = None


class CopilotPending(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    error: Literal["authorization_pending", "slow_down"]
    interval: int | None = Field(default=None, strict=True, gt=0, le=3600)


class _OAuthFailure(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    error: str = Field(min_length=1, max_length=128, pattern=r"^[a-z_]+$")


class CopilotAccountAPI(Protocol):
    async def start(self, client_id: str) -> GitHubCopilotDeviceAuthorization: ...
    async def poll(self, *, client_id: str, device_code: str) -> CopilotGrant | CopilotPending: ...
    async def models(self, token: str) -> list[CopilotModel]: ...


class CopilotAccountClient:
    """One bounded HTTP operation at a time; callers persist and rate-limit polling."""

    def __init__(self, http: httpx2.AsyncClient | None = None) -> None:
        self.http = http

    @asynccontextmanager
    async def _http(self) -> AsyncGenerator[httpx2.AsyncClient]:
        if self.http is not None:
            yield self.http
        else:
            async with httpx2.AsyncClient(timeout=httpx2.Timeout(15, connect=5)) as http:
                yield http

    async def start(self, client_id: str) -> GitHubCopilotDeviceAuthorization:
        try:
            return await GitHubCopilotOAuthFlow(client_id=client_id, http_client=self.http).start()
        except (UserError, httpx2.HTTPError) as failed:
            raise BadRequestError(
                message="GitHub device authorization could not start. Check the AgenticOS OAuth App, device-flow setting and network."
            ) from failed

    async def poll(self, *, client_id: str, device_code: str) -> CopilotGrant | CopilotPending:
        async with self._http() as http:
            response = await http.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json", **HEADERS},
                follow_redirects=False,
            )
        if response.status_code != 200:
            raise BadRequestError(
                message="GitHub device authorization failed. Start sign-in again."
            )
        try:
            return self._poll_result(response)
        except ValueError as invalid:
            raise BadRequestError(
                message="GitHub returned an invalid device token response."
            ) from invalid

    @staticmethod
    def _poll_result(response: httpx2.Response) -> CopilotGrant | CopilotPending:
        payload: object = response.json()
        if isinstance(payload, Mapping) and "error" in payload:
            failure = _OAuthFailure.model_validate(payload)
            if failure.error in {"authorization_pending", "slow_down"}:
                return CopilotPending.model_validate(payload)
            reason = {
                "access_denied": "GitHub authorization was denied.",
                "expired_token": "GitHub device authorization expired.",
                "device_flow_disabled": "Enable device flow for the AgenticOS OAuth App.",
            }.get(failure.error, "GitHub refused device authorization. Start sign-in again.")
            raise BadRequestError(message=reason)
        grant = CopilotGrant.model_validate(payload)
        if (
            grant.expires_in is not None
            or grant.refresh_token is not None
            or grant.refresh_token_expires_in is not None
        ):
            raise BadRequestError(
                message="This grant requires token renewal. Configure a non-expiring GitHub OAuth App grant; expiring GitHub App grants are not supported by this connection."
            )
        return grant

    async def models(self, token: str) -> list[CopilotModel]:
        token = bearer_token(token)
        async with self._http() as http:
            response = await http.get(
                f"{BASE_URL}/models",
                headers={**HEADERS, "Authorization": f"Bearer {token}"},
                follow_redirects=False,
            )
        if response.status_code != 200:
            raise BadRequestError(
                message="Copilot did not accept this account and AgenticOS application. Check subscription, organization policy and OAuth application access."
            )
        try:
            models = _Models.model_validate_json(response.content)
        except ValidationError as invalid:
            raise BadRequestError(message="Copilot returned an invalid model catalog.") from invalid
        return [model for model in models.data if "/chat/completions" in model.supported_endpoints]
