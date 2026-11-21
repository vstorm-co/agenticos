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

import httpx
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, JsonValue
from starlette.background import BackgroundTask

from ._instances import GatewayError, Instance, Supervisor

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
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(
            method,
            f"{instance.base_url}/v8/management{path}",
            params=params,
            json=json,
            headers={"Authorization": f"Bearer {instance.management_key}"},
        )
    if response.status_code >= 400:
        raise GatewayError(
            "The account service refused this request",
            status=502 if response.status_code >= 500 else 400,
        )
    try:
        return response.json()
    except ValueError:
        return None


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
        instance = await held.enter_async_context(supervisor.use(scope))
        client = await held.enter_async_context(
            httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10))
        )
        try:
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
        except httpx.HTTPError:
            await held.aclose()
            raise GatewayError("The account gateway is unavailable", status=502) from None
        held.push_async_callback(upstream.aclose)
        return StreamingResponse(
            upstream.aiter_raw(),
            status_code=upstream.status_code,
            headers={
                key: value
                for key, value in upstream.headers.items()
                if key.lower() not in _HOP | {"content-length"}
            },
            background=BackgroundTask(held.aclose),
        )

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
        return {
            "items": [
                {key: row[key] for key in _ACCOUNT_FIELDS if key in row}
                for row in rows
                if isinstance(row, dict)
            ]
        }

    @app.delete("/scopes/{scope}/accounts/{name}", dependencies=guarded)
    async def remove_account(scope: str, name: str) -> JsonValue:
        _checked(_ACCOUNT, name, "account")
        async with supervisor.use(scope) as instance:
            await _management(instance, "DELETE", "/credentials", params={"name": name})
        return {"removed": True}

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

    @app.delete("/scopes/{scope}", dependencies=guarded)
    async def wipe(scope: str) -> JsonValue:
        await supervisor.wipe(scope)
        return {"wiped": True}

    return app
