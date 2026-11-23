"""The gateway's HTTP surface: model traffic and account sign-in, per scope.

Only the AgenticOS backend talks to this service, with one shared token. The
backend decides the scope from the organization and the person; nothing a
browser sends ever names one. Every route below forwards to that scope's own
CLIProxyAPI process with the process's private keys, so a caller never learns
them and one scope's keys cannot reach another's process.
"""

import asyncio
import contextlib
import re
import secrets
from collections.abc import AsyncGenerator
from typing import Annotated

import anyio
import httpx
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, JsonValue
from starlette.types import Receive, Scope, Send

from app.subscription_gateway._account_data import account_prefix, account_usage

from ._instances import GatewayError, Instance, Supervisor
from ._usage import antigravity_usage, claude_usage, codex_usage, kimi_usage

PROVIDERS = frozenset({"claude", "codex", "antigravity", "kimi", "kimi-ai", "xai", "devin", "meta"})
"""Sign-ins CLIProxyAPI's management API supports; anything else is refused."""

_ACCOUNT = re.compile(r"^[A-Za-z0-9._@+-]{1,200}$")
_STATE = re.compile(r"^[A-Za-z0-9._~-]{1,200}$")
_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "transfer-encoding",
        "te",  # codespell:ignore te
        "trailer",
        "upgrade",
        "host",
    }
)
_ACCOUNT_FIELDS = ("name", "provider", "label", "email", "status", "disabled", "unavailable")


class LoginStart(BaseModel):
    provider: str


class AccountModelSelection(BaseModel):
    model: str = Field(min_length=1, max_length=222, pattern=r"^[^\s]+$")


class LoginCallback(BaseModel):
    redirect_url: str = Field(min_length=1, max_length=8192)


def _checked(pattern: re.Pattern[str], value: str, what: str) -> str:
    if not pattern.fullmatch(value):
        raise GatewayError(f"Invalid {what}")
    return value


async def _management(
    instance: Instance,
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    json: dict[str, str] | None = None,
) -> JsonValue:
    """One management call to the scope's own process; its errors stay generic."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method,
                f"{instance.base_url}/v8/management{path}",
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {instance.management_key}"},
            )
    except httpx.TimeoutException:
        raise GatewayError("The account service timed out; try again", status=504) from None
    except httpx.HTTPError:
        raise GatewayError("The account service is unavailable; try again", status=502) from None
    if response.status_code >= 400:
        raise GatewayError(
            "The account service refused this request",
            status=502 if response.status_code >= 500 else 400,
        )
    try:
        return response.json()
    except ValueError:
        return None


async def _account(instance: Instance, name: str) -> dict[str, JsonValue]:
    listed = await _management(instance, "GET", "/credentials")
    files = listed.get("files") if isinstance(listed, dict) else None
    if not isinstance(files, list):
        raise GatewayError("The account service did not list accounts", status=502)
    for row in files:
        if isinstance(row, dict) and row.get("name") == name:
            if row.get("disabled") or row.get("unavailable"):
                raise GatewayError("Reconnect this account before selecting a model", status=409)
            return row
    raise GatewayError("This account is not connected", status=404)


def _public_account(scope: str, row: dict[str, JsonValue]) -> dict[str, JsonValue]:
    name = row.get("name")
    provider = row.get("provider")
    if not isinstance(name, str) or not isinstance(provider, str):
        raise GatewayError("The account service sent an invalid account", status=502)
    return {
        **{key: row[key] for key in _ACCOUNT_FIELDS if key in row},
        "model_prefix": account_prefix(scope, name),
        "usage": account_usage(provider, row.get("quota")).model_dump(mode="json"),
    }


def _model_ids(listed: JsonValue) -> list[str]:
    models = listed.get("models") if isinstance(listed, dict) else None
    if not isinstance(models, list):
        raise GatewayError("The account service did not list models", status=502)
    ids: list[str] = []
    for row in models:
        if isinstance(row, dict) and isinstance(model_id := row.get("id"), str):
            ids.append(model_id)
    return ids


class _ForwardedResponse(StreamingResponse):
    """Own the upstream lease even when streaming or ASGI delivery fails."""

    def __init__(self, upstream: httpx.Response, held: contextlib.AsyncExitStack) -> None:
        self.held = held
        super().__init__(
            upstream.aiter_raw(),
            status_code=upstream.status_code,
            headers={
                key: value
                for key, value in upstream.headers.items()
                if key.lower() not in _HOP | {"content-length"}
            },
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self.held.aclose()


def create_app(supervisor: Supervisor, token: str, *, reap_seconds: float = 60) -> FastAPI:
    async def authorized(authorization: Annotated[str, Header()] = "") -> None:
        expected = f"Bearer {token}"
        if not secrets.compare_digest(authorization.encode(), expected.encode()):
            raise GatewayError("Unauthorized", status=401)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        async def reaper() -> None:
            while True:
                await asyncio.sleep(reap_seconds)
                await supervisor.reap()

        task = asyncio.create_task(reaper())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await supervisor.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    guarded = [Depends(authorized)]

    @app.exception_handler(GatewayError)
    async def refused(_request: Request, error: GatewayError) -> JSONResponse:
        return JSONResponse({"detail": error.message}, status_code=error.status)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.api_route("/scopes/{scope}/v1/{path:path}", methods=["GET", "POST"], dependencies=guarded)
    async def forward(scope: str, path: str, request: Request) -> Response:
        # Held until the response body has been streamed, so an idle reaper
        # cannot stop a process in the middle of an answer.
        held = contextlib.AsyncExitStack()
        try:
            instance = await held.enter_async_context(supervisor.use(scope))
            client = await held.enter_async_context(
                httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10))
            )
            upstream = await client.send(
                client.build_request(
                    request.method,
                    f"{instance.base_url}/v1/{path}",
                    params=request.query_params,
                    content=await request.body(),
                    headers={
                        **{
                            key: value
                            for key, value in request.headers.items()
                            if key.lower() not in _HOP | {"authorization", "content-length"}
                        },
                        "Authorization": f"Bearer {instance.client_key}",
                    },
                ),
                stream=True,
            )
            held.push_async_callback(upstream.aclose)
            response = _ForwardedResponse(upstream, held)
        except BaseException as failed:
            with anyio.CancelScope(shield=True):
                await held.aclose()
            if isinstance(failed, httpx.HTTPError):
                raise GatewayError("The account gateway is unavailable", status=502) from None
            raise
        return response

    @app.post("/scopes/{scope}/logins", dependencies=guarded)
    async def start_login(scope: str, body: LoginStart) -> JsonValue:
        if body.provider not in PROVIDERS:
            raise GatewayError("This account type is not supported")
        async with supervisor.use(scope) as instance:
            started = await _management(
                instance, "GET", "/oauth/auth-url", params={"provider": body.provider}
            )
        if not isinstance(started, dict):
            raise GatewayError("The account service did not start a sign-in", status=502)
        return {
            key: started[key]
            for key in ("url", "state", "flow", "user_code", "expires_in")
            if key in started
        }

    @app.get("/scopes/{scope}/logins/{state}", dependencies=guarded)
    async def login_status(scope: str, state: str) -> JsonValue:
        _checked(_STATE, state, "sign-in")
        async with supervisor.use(scope) as instance:
            status = await _management(instance, "GET", "/oauth/status", params={"state": state})
        if not isinstance(status, dict):
            raise GatewayError("The account service did not report the sign-in", status=502)
        return {key: status[key] for key in ("status", "error") if key in status}

    @app.post("/scopes/{scope}/logins/{state}/callback", dependencies=guarded)
    async def login_callback(scope: str, state: str, body: LoginCallback) -> JsonValue:
        _checked(_STATE, state, "sign-in")
        async with supervisor.use(scope) as instance:
            await _management(
                instance,
                "POST",
                "/oauth/callback",
                json={"state": state, "redirect_url": body.redirect_url},
            )
        return {"accepted": True}

    @app.delete("/scopes/{scope}/logins/{state}", dependencies=guarded)
    async def cancel_login(scope: str, state: str) -> JsonValue:
        _checked(_STATE, state, "sign-in")
        async with supervisor.use(scope) as instance:
            await _management(instance, "DELETE", "/oauth/session", params={"state": state})
        return {"cancelled": True}

    @app.get("/scopes/{scope}/accounts", dependencies=guarded)
    async def accounts(scope: str) -> JsonValue:
        async with supervisor.use(scope) as instance:
            listed = await _management(instance, "GET", "/credentials")
        files = listed.get("files") if isinstance(listed, dict) else None
        rows = files if isinstance(files, list) else []
        return {"items": [_public_account(scope, row) for row in rows if isinstance(row, dict)]}

    @app.delete("/scopes/{scope}/accounts/{name}", dependencies=guarded)
    async def remove_account(scope: str, name: str) -> JsonValue:
        _checked(_ACCOUNT, name, "account")
        async with supervisor.use(scope) as instance:
            await _management(instance, "DELETE", "/credentials", params={"name": name})
        return {"removed": True}

    @app.get("/scopes/{scope}/accounts/{name}/usage", dependencies=guarded)
    async def usage(scope: str, name: str) -> JsonValue:
        _checked(_ACCOUNT, name, "account")
        async with supervisor.use(scope) as instance:
            row = await _account(instance, name)
            provider = row.get("provider")
            if provider == "antigravity":
                auth_index = row.get("auth_index")
                if not isinstance(auth_index, str) or not auth_index:
                    raise GatewayError(
                        "Reconnect this account before reading its limits", status=409
                    )
                return (await antigravity_usage(instance, auth_index)).model_dump(mode="json")
            if provider in {"claude", "anthropic"}:
                auth_index = row.get("auth_index")
                if not isinstance(auth_index, str) or not auth_index:
                    raise GatewayError(
                        "Reconnect this account before reading its limits", status=409
                    )
                return (await claude_usage(instance, auth_index)).model_dump(mode="json")
            if provider in {"kimi", "kimi-ai"}:
                auth_index = row.get("auth_index")
                if not isinstance(auth_index, str) or not auth_index:
                    raise GatewayError(
                        "Reconnect this account before reading its limits", status=409
                    )
                return (
                    await kimi_usage(instance, auth_index, international=provider == "kimi-ai")
                ).model_dump(mode="json")
            if provider == "codex":
                claims = row.get("id_token")
                account_id = claims.get("chatgpt_account_id") if isinstance(claims, dict) else None
                auth_index = row.get("auth_index")
                if (
                    isinstance(account_id, str)
                    and isinstance(auth_index, str)
                    and re.fullmatch(r"[A-Za-z0-9_-]{1,256}", account_id)
                ):
                    return (await codex_usage(instance, auth_index, account_id)).model_dump(
                        mode="json"
                    )
            return account_usage(str(provider), row.get("quota")).model_dump(mode="json")

    @app.get("/scopes/{scope}/accounts/{name}/models", dependencies=guarded)
    async def account_models(scope: str, name: str) -> JsonValue:
        _checked(_ACCOUNT, name, "account")
        async with supervisor.use(scope) as instance:
            listed = await _management(
                instance, "GET", "/credentials/models", params={"name": name}
            )
        if not isinstance(listed, dict) or not isinstance(listed.get("models"), list):
            raise GatewayError("The account service did not list models", status=502)
        return {"items": listed["models"]}

    @app.post("/scopes/{scope}/accounts/{name}/model-selection", dependencies=guarded)
    async def select_account_model(scope: str, name: str, body: AccountModelSelection) -> JsonValue:
        _checked(_ACCOUNT, name, "account")
        prefix = account_prefix(scope, name)
        async with supervisor.use(scope) as instance:
            await _account(instance, name)
            listed = await _management(
                instance, "GET", "/credentials/models", params={"name": name}
            )
            if body.model not in {model.removeprefix(prefix + "/") for model in _model_ids(listed)}:
                raise GatewayError("This model is not advertised by the selected account")
            # CLIProxyAPI routes a prefixed model only to that credential. Unlike
            # toggling enabled accounts, this cannot redirect another conversation.
            await _management(
                instance, "PATCH", "/credentials/fields", json={"name": name, "prefix": prefix}
            )
            pinned = f"{prefix}/{body.model}"
            refreshed = await _management(
                instance, "GET", "/credentials/models", params={"name": name}
            )
            if pinned not in _model_ids(refreshed):
                raise GatewayError(
                    "The selected account's model route is not ready; retry shortly", status=503
                )
        return {"model": pinned}

    @app.delete("/scopes/{scope}", dependencies=guarded)
    async def wipe(scope: str) -> JsonValue:
        await supervisor.wipe(scope)
        return {"wiped": True}

    return app
