"""The signed-in person's own subscription accounts in the current organization.

Every route acts on the caller's own gateway scope, derived from the
organization and the person; no path parameter names whose accounts these are.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Path, status

from app.api.deps import Auth, SubscriptionAccountSvc
from app.clients.subscription_gateway import SelectedAccountModel, configured_gateway
from app.schemas.subscription_account import (
    SubscriptionAccountList,
    SubscriptionModelSelection,
    SubscriptionSignIn,
    SubscriptionSignInCallback,
    SubscriptionSignInStart,
    SubscriptionSignInStatus,
)
from app.subscription_gateway.contracts import AccountUsage

router = APIRouter()

SignInState = Annotated[str, Path(pattern=r"^[A-Za-z0-9._~-]{1,200}$")]
AccountName = Annotated[str, Path(pattern=r"^[A-Za-z0-9._@+-]{1,200}$")]


@router.get("", response_model=SubscriptionAccountList)
async def mine(ctx: Auth, service: SubscriptionAccountSvc) -> Any:
    """List the caller's signed-in accounts; `enabled` is false where the gateway is off."""
    if configured_gateway() is None:
        return {"enabled": False, "items": []}
    return {"enabled": True, "items": await service.accounts(ctx)}


@router.post("/sign-ins", response_model=SubscriptionSignIn, status_code=status.HTTP_201_CREATED)
async def start_sign_in(
    data: SubscriptionSignInStart, ctx: Auth, service: SubscriptionAccountSvc
) -> Any:
    """Start signing in to one provider account; the answer says where and how."""
    return await service.start_login(ctx, data.provider)


@router.get("/sign-ins/{state}", response_model=SubscriptionSignInStatus)
async def sign_in_status(state: SignInState, ctx: Auth, service: SubscriptionAccountSvc) -> Any:
    """Whether the sign-in finished: `wait`, `ok` or `error`."""
    return await service.login_status(ctx, state)


@router.post("/sign-ins/{state}/callback", status_code=status.HTTP_204_NO_CONTENT)
async def complete_sign_in(
    state: SignInState,
    data: SubscriptionSignInCallback,
    ctx: Auth,
    service: SubscriptionAccountSvc,
) -> None:
    """Finish a browser sign-in with the address the provider redirected to."""
    await service.complete_login(ctx, state, data.redirect_url)


@router.delete("/sign-ins/{state}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_sign_in(state: SignInState, ctx: Auth, service: SubscriptionAccountSvc) -> None:
    """Abandon a sign-in that has not finished."""
    await service.cancel_login(ctx, state)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(name: AccountName, ctx: Auth, service: SubscriptionAccountSvc) -> None:
    """Sign one account out and delete its tokens."""
    await service.remove(ctx, name)


@router.get("/{name}/models", response_model=list[str])
async def account_models(name: AccountName, ctx: Auth, service: SubscriptionAccountSvc) -> Any:
    """List models advertised by one of the caller's accounts, without guessing from model IDs."""
    return await service.account_models(ctx, name)


@router.post("/{name}/model-selection", response_model=SelectedAccountModel)
async def select_account_model(
    name: AccountName, data: SubscriptionModelSelection, ctx: Auth, service: SubscriptionAccountSvc
) -> Any:
    """Select a listed model on this account, returning its opaque account-specific route."""
    return await service.select_account_model(ctx, name, data.model)


@router.get("/{name}/usage", response_model=AccountUsage)
async def account_usage(name: AccountName, ctx: Auth, service: SubscriptionAccountSvc) -> Any:
    """Read per-account subscription windows and reset times without making a model call."""
    return await service.account_usage(ctx, name)
