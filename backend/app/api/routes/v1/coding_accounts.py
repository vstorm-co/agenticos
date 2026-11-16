"""The signed-in person's coding accounts in the current organization."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import Auth, CodingAccountSvc, OpenAICodexSvc
from app.schemas.coding_account import (
    CodingAccountCreate,
    CodingAccountList,
    CodingAccountOAuthComplete,
    CodingAccountOAuthStart,
    CodingAccountRead,
    CodingAccountUpdate,
)
from app.services.coding_accounts import account_owner

router = APIRouter()


@router.get("", response_model=CodingAccountList)
async def mine(ctx: Auth, service: CodingAccountSvc) -> Any:
    """List only the caller's account metadata, never credentials."""
    return {"items": await service.mine(ctx)}


@router.post("", response_model=CodingAccountRead, status_code=status.HTTP_201_CREATED)
async def connect(data: CodingAccountCreate, ctx: Auth, service: CodingAccountSvc) -> Any:
    """Connect a private provider key or Claude subscription token."""
    return await service.create(ctx, data)


@router.post("/codex/sign-in", response_model=CodingAccountOAuthStart)
async def start_codex(ctx: Auth, service: OpenAICodexSvc) -> Any:
    """Start a fresh, caller-bound ChatGPT grant; existing CLI files are not imported."""
    account_owner(ctx)
    return {"authorization_url": await service.start_sign_in(ctx)}


@router.post(
    "/codex/complete", response_model=CodingAccountRead, status_code=status.HTTP_201_CREATED
)
async def complete_codex(
    data: CodingAccountOAuthComplete,
    ctx: Auth,
    oauth: OpenAICodexSvc,
    service: CodingAccountSvc,
) -> Any:
    """Store the new ChatGPT grant under the caller's own vault scope."""
    account_owner(ctx)
    secret = await oauth.finish_personal_sign_in(ctx, data.callback_url.get_secret_value())
    return await service.save(
        ctx, harness="codex", label=data.label, secret=secret, enabled=data.enabled
    )


@router.patch("/{account_id}", response_model=CodingAccountRead)
async def consent(
    account_id: UUID, data: CodingAccountUpdate, ctx: Auth, service: CodingAccountSvc
) -> Any:
    """Enable or revoke use in this organization, checking the reviewed generation."""
    return await service.update(ctx, account_id, data)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(account_id: UUID, ctx: Auth, service: CodingAccountSvc) -> None:
    """Remove AgenticOS's credentials and permission to start tasks with this account."""
    await service.disconnect(ctx, account_id)
