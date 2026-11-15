"""Personal Claude subscription sign-in through the official native runtime."""

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import Auth, ClaudeSubscriptionSvc, no_store_response, require
from app.core.permissions import Perm
from app.schemas.claude_subscription import (
    ClaudeSubscriptionLoginCode,
    ClaudeSubscriptionLoginControl,
    ClaudeSubscriptionRead,
)

router = APIRouter(
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE)), Depends(no_store_response)]
)


@router.get("/claude", response_model=ClaudeSubscriptionRead)
async def status(service: ClaudeSubscriptionSvc, ctx: Auth) -> Any:
    """The current user's native connection in the active organization."""
    return await service.status(ctx)


@router.post("/claude/login", response_model=ClaudeSubscriptionRead)
async def login(service: ClaudeSubscriptionSvc, ctx: Auth) -> Any:
    """Start the native provider sign-in; the caller completes it on Anthropic's page."""
    return await service.login(ctx)


@router.post("/claude/login/code", response_model=ClaudeSubscriptionRead)
async def submit_code(
    data: ClaudeSubscriptionLoginCode, service: ClaudeSubscriptionSvc, ctx: Auth
) -> Any:
    """Pass a one-time code to its pending native login, without storing it."""
    return await service.code(ctx, data)


@router.post("/claude/login/cancel", response_model=ClaudeSubscriptionRead)
async def cancel_login(
    data: ClaudeSubscriptionLoginControl, service: ClaudeSubscriptionSvc, ctx: Auth
) -> Any:
    """Cancel the caller's pending login; another person's login is unreachable."""
    return await service.cancel(ctx, data)


@router.post("/claude/disconnect", response_model=ClaudeSubscriptionRead)
async def disconnect(service: ClaudeSubscriptionSvc, ctx: Auth) -> Any:
    """Sign out through the native client; existing model profiles remain private."""
    return await service.disconnect(ctx)
