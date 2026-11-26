"""The bundled subscription gateway, as the backend calls it.

The gateway (`app.subscription_gateway`) runs one CLIProxyAPI per scope and
accepts only this deployment's shared token. A scope is an opaque digest the
backend derives from an organization and a person
(`app.services.subscription_accounts.gateway_scope`); nothing here takes one
from a browser.
"""

from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from app.core.config import settings
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.subscription_gateway.contracts import AccountUsage

type GatewayProvider = Literal[
    "claude", "codex", "antigravity", "kimi", "kimi-ai", "xai", "devin", "meta"
]
"""Every sign-in the gateway offers; CLIProxyAPI's management API names them so."""


class _Answer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class LoginStarted(_Answer):
    url: str
    state: str
    flow: str | None = None
    user_code: str | None = None
    expires_in: int | None = None


class LoginStatus(_Answer):
    status: str
    error: str | None = None


class GatewayAccount(_Answer):
    name: str
    provider: str
    label: str | None = None
    email: str | None = None
    status: str | None = None
    disabled: bool = False
    unavailable: bool = False
    model_prefix: str | None = None
    usage: AccountUsage = Field(default_factory=AccountUsage)


class _Accounts(_Answer):
    items: list[GatewayAccount]


class _Model(_Answer):
    id: str


class _Models(_Answer):
    data: list[_Model]


class SelectedAccountModel(_Answer):
    model: str


class _AccountModels(_Answer):
    items: list[_Model]


class SubscriptionGateway:
    """One deployment's gateway. Refusals keep the gateway's own, already generic, message."""

    def __init__(
        self, base_url: str, token: str, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._transport = transport

    def model_endpoint(self, scope: str) -> str:
        """The OpenAI-compatible endpoint serving this scope's accounts."""
        return f"{self.base_url}/scopes/{scope}/v1"

    @property
    def token(self) -> str:
        return self._token

    async def _call[T](
        self,
        answer: TypeAdapter[T],
        method: str,
        path: str,
        *,
        body: dict[str, str] | None = None,
    ) -> T:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=60, transport=self._transport
            ) as client:
                response = await client.request(
                    method, path, json=body, headers={"Authorization": f"Bearer {self._token}"}
                )
        except httpx.HTTPError:
            raise ExternalServiceError(
                message="The subscription gateway is unreachable. Try again shortly."
            ) from None
        if 400 <= response.status_code < 500:
            raise BadRequestError(
                message=_detail(response, "The subscription gateway refused this")
            )
        if response.status_code >= 500:
            raise ExternalServiceError(
                message=_detail(response, "The subscription gateway could not do this")
            )
        try:
            return answer.validate_json(response.content)
        except ValidationError:
            raise ExternalServiceError(
                message="The subscription gateway sent an answer this version cannot read"
            ) from None

    async def start_login(self, scope: str, provider: GatewayProvider) -> LoginStarted:
        return await self._call(
            TypeAdapter(LoginStarted),
            "POST",
            f"/scopes/{scope}/logins",
            body={"provider": provider},
        )

    async def login_status(self, scope: str, state: str) -> LoginStatus:
        return await self._call(TypeAdapter(LoginStatus), "GET", f"/scopes/{scope}/logins/{state}")

    async def complete_login(self, scope: str, state: str, redirect_url: str) -> None:
        await self._call(
            TypeAdapter(JsonValue),
            "POST",
            f"/scopes/{scope}/logins/{state}/callback",
            body={"redirect_url": redirect_url},
        )

    async def cancel_login(self, scope: str, state: str) -> None:
        await self._call(TypeAdapter(JsonValue), "DELETE", f"/scopes/{scope}/logins/{state}")

    async def accounts(self, scope: str) -> list[GatewayAccount]:
        listed = await self._call(TypeAdapter(_Accounts), "GET", f"/scopes/{scope}/accounts")
        return listed.items

    async def remove_account(self, scope: str, name: str) -> None:
        await self._call(TypeAdapter(JsonValue), "DELETE", f"/scopes/{scope}/accounts/{name}")

    async def models(self, scope: str) -> list[str]:
        listed = await self._call(TypeAdapter(_Models), "GET", f"/scopes/{scope}/v1/models")
        return [model.id for model in listed.data]

    async def account_usage(self, scope: str, name: str) -> AccountUsage:
        return await self._call(
            TypeAdapter(AccountUsage), "GET", f"/scopes/{scope}/accounts/{name}/usage"
        )

    async def account_models(self, scope: str, name: str) -> list[str]:
        listed = await self._call(
            TypeAdapter(_AccountModels), "GET", f"/scopes/{scope}/accounts/{name}/models"
        )
        return [model.id for model in listed.items]

    async def select_account_model(self, scope: str, name: str, model: str) -> SelectedAccountModel:
        return await self._call(
            TypeAdapter(SelectedAccountModel),
            "POST",
            f"/scopes/{scope}/accounts/{name}/model-selection",
            body={"model": model},
        )

    async def wipe(self, scope: str) -> None:
        await self._call(TypeAdapter(JsonValue), "DELETE", f"/scopes/{scope}")


def _detail(response: httpx.Response, fallback: str) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError, AttributeError:
        return fallback
    return detail if isinstance(detail, str) and detail else fallback


def configured_gateway() -> SubscriptionGateway | None:
    """This deployment's gateway, or None where the operator has not enabled one."""
    if not settings.SUBSCRIPTION_GATEWAY_URL:
        return None
    return SubscriptionGateway(
        settings.SUBSCRIPTION_GATEWAY_URL, settings.SUBSCRIPTION_GATEWAY_TOKEN
    )
