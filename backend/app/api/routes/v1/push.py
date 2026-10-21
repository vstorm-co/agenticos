"""Web Push in this browser: the key it subscribes with, the subscription, a test (#2097)."""

from typing import Any

from fastapi import APIRouter, Header, Query, status

from app.api.deps import CurrentUser, DeploymentSettingsSvc, WebPushSvc
from app.schemas.push import PushKeyRead, PushSubscriptionCreate, PushTestRead

router = APIRouter()


@router.get("/key", response_model=PushKeyRead)
async def push_key(_user: CurrentUser, push: WebPushSvc) -> Any:
    """The deployment's VAPID public key, which `pushManager.subscribe` takes as
    its `applicationServerKey`. Made the first time it is asked for."""
    return PushKeyRead(public_key=await push.public_key())


@router.post("/subscriptions", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def subscribe(
    subscription: PushSubscriptionCreate,
    current_user: CurrentUser,
    push: WebPushSvc,
    user_agent: str | None = Header(default=None),
) -> None:
    """Push to this browser from now on. Its endpoint must belong to a browser
    push service - Google's, Mozilla's, Apple's or Microsoft's."""
    await push.subscribe(current_user.id, subscription, user_agent=user_agent)


@router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def unsubscribe(
    current_user: CurrentUser,
    push: WebPushSvc,
    endpoint: str = Query(max_length=2048),
) -> None:
    """Stop pushing to this browser. 404 when it was not subscribed."""
    await push.unsubscribe(current_user.id, endpoint)


@router.post("/test", response_model=PushTestRead)
async def send_test(
    current_user: CurrentUser, push: WebPushSvc, deployment: DeploymentSettingsSvc
) -> Any:
    """A push to every browser of the caller's, to see that it arrives. 404 when
    none is subscribed."""
    outcome = await push.send_test(current_user.id, app_name=await deployment.effective_app_name())
    return PushTestRead(sent=outcome.sent, gone=outcome.gone, failed=outcome.failed)
