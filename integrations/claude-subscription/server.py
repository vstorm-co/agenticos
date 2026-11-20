"""Private runtime RPC. Only the T3OS API may choose an authenticated owner."""

import asyncio
import contextlib
import os
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from isolation import Homes, Owner, RuntimeFailure
from runtime import CLI_PATH, ClaudeRuntime
from schemas import (
    CodeRequest,
    ConnectionStatus,
    InferRequest,
    InferResult,
    LoginRequest,
    OwnerRequest,
)
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 1024 * 1024


class RequestGuard:
    def __init__(self, app: ASGIApp, *, service_key: str) -> None:
        self.app = app
        self.key = service_key.encode("ascii")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or (
            scope["method"] == "GET" and scope["path"] == "/health"
        ):
            await self.app(scope, receive, send)
            return
        keys = [
            value for key, value in scope["headers"] if key == b"x-claude-runtime-key"
        ]
        if len(keys) != 1 or not secrets.compare_digest(keys[0], self.key):
            await JSONResponse(
                {"error": {"code": "CLAUDE_ACCESS_DENIED"}}, status_code=403
            )(scope, receive, send)
            return
        received = 0

        async def bounded_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:
                    raise HTTPException(status_code=413)
            return message

        await self.app(scope, bounded_receive, send)


def create_app(runtime: ClaudeRuntime, service_key: str) -> FastAPI:
    if len(service_key) < 32 or not service_key.isascii():
        raise RuntimeError("Native runtime requires a private service key")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(RequestGuard, service_key=service_key)

    @app.exception_handler(RuntimeFailure)
    async def runtime_error(_request: Request, error: RuntimeFailure) -> JSONResponse:
        return JSONResponse({"error": {"code": error.code}}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        # Validation input can contain the pasted code or a whole conversation.
        return JSONResponse(
            {"error": {"code": "CLAUDE_INVALID_REQUEST"}}, status_code=422
        )

    @app.exception_handler(HTTPException)
    async def invalid_http_request(
        _request: Request, error: HTTPException
    ) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "CLAUDE_INVALID_REQUEST"}}, status_code=error.status_code
        )

    @app.exception_handler(OSError)
    async def unavailable(_request: Request, _error: OSError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "CLAUDE_RUNTIME_UNAVAILABLE"}}, status_code=503
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "provider": "claude"}

    @app.post("/v1/status", response_model=ConnectionStatus)
    async def status(body: OwnerRequest) -> ConnectionStatus:
        return await runtime.status(Owner(body.organization_id, body.user_id))

    @app.post("/v1/login", response_model=ConnectionStatus)
    async def login(body: OwnerRequest) -> ConnectionStatus:
        return await runtime.start_login(Owner(body.organization_id, body.user_id))

    @app.post("/v1/login/code", response_model=ConnectionStatus)
    async def code(body: CodeRequest) -> ConnectionStatus:
        return await runtime.submit_code(
            Owner(body.organization_id, body.user_id), body.login_id, body.code
        )

    @app.post("/v1/login/cancel", response_model=ConnectionStatus)
    async def cancel(body: LoginRequest) -> ConnectionStatus:
        return await runtime.cancel_login(
            Owner(body.organization_id, body.user_id), body.login_id
        )

    @app.post("/v1/disconnect", response_model=ConnectionStatus)
    async def disconnect(body: OwnerRequest) -> ConnectionStatus:
        return await runtime.disconnect(Owner(body.organization_id, body.user_id))

    @app.post("/v1/infer", response_model=InferResult)
    async def infer(body: InferRequest, request: Request) -> InferResult:
        task = asyncio.create_task(
            runtime.infer(Owner(body.organization_id, body.user_id), body)
        )
        disconnected = False

        async def watch_connection() -> None:
            nonlocal disconnected
            while not task.done():
                if await request.is_disconnected():
                    disconnected = True
                    task.cancel()
                    return
                await asyncio.sleep(0.25)

        monitor = asyncio.create_task(watch_connection())
        try:
            return await task
        except asyncio.CancelledError:
            if disconnected:
                raise RuntimeFailure("CLAUDE_REQUEST_CANCELLED", 499) from None
            raise
        finally:
            monitor.cancel()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return app


def from_environment() -> FastAPI:
    key = os.environ.get("CLAUDE_SUBSCRIPTION_SERVICE_KEY", "")
    if len(key) < 32 or not key.isascii():
        raise RuntimeError("Native runtime requires a private service key")
    if not os.access(CLI_PATH, os.X_OK) or not os.access("/usr/bin/script", os.X_OK):
        raise RuntimeError(
            "Native runtime requires the pinned Claude client and util-linux script"
        )
    runtime = ClaudeRuntime(Homes(Path("/state")), maximum=4)
    return create_app(runtime, key)
