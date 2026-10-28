"""Push (#2097): Web Push in this browser - the key it subscribes with, the
subscription - an iPhone's APNs token, the organization's APNs key, and a test
of all of them."""

from typing import Any

from fastapi import APIRouter, Header, Query, status

from app.api.deps import (
    ApnsSvc,
    CurrentAppAdmin,
    CurrentSessionId,
    CurrentUser,
    DeploymentSettingsSvc,
    PushSvc,
    WebPushSvc,
)
from app.schemas.push import (
    ApnsDeviceCreate,
    ApnsKeyUpdate,
    ApnsRead,
    PushFocusUpdate,
    PushKeyRead,
    PushPreferencesRead,
    PushPreferencesUpdate,
    PushSubscriptionCreate,
    PushTestRead,
)

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
    session_id: CurrentSessionId,
    user_agent: str | None = Header(default=None),
) -> None:
    """Push to this browser from now on. Its endpoint must belong to a browser
    push service - Google's, Mozilla's, Apple's or Microsoft's."""
    await push.subscribe(
        current_user.id, subscription, user_agent=user_agent, session_id=session_id
    )


@router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def unsubscribe(
    current_user: CurrentUser,
    push: WebPushSvc,
    endpoint: str = Query(max_length=2048),
) -> None:
    """Stop pushing to this browser. 404 when it was not subscribed."""
    await push.unsubscribe(current_user.id, endpoint)


@router.get("/apns", response_model=ApnsRead)
async def apns_status(_user: CurrentUser, apns: ApnsSvc) -> Any:
    """Whether iPhones can be pushed to, and with whose key: the iOS app offers
    push only when they can. Never the key."""
    return await apns.read()


@router.put("/apns", response_model=ApnsRead)
async def set_apns_key(
    data: ApnsKeyUpdate, user: CurrentAppAdmin, deployment: DeploymentSettingsSvc
) -> Any:
    """Set the organization's APNs key - the `.p8` of the Apple developer
    account its iOS app is signed with - replacing any before it."""
    return await deployment.set_apns_key(actor_user_id=user.id, data=data)


@router.delete("/apns", response_model=ApnsRead)
async def clear_apns_key(user: CurrentAppAdmin, deployment: DeploymentSettingsSvc) -> Any:
    """Stop pushing to iPhones."""
    return await deployment.clear_apns_key(actor_user_id=user.id)


@router.post("/apns/devices", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def register_iphone(
    device: ApnsDeviceCreate,
    current_user: CurrentUser,
    apns: ApnsSvc,
    session_id: CurrentSessionId,
) -> None:
    """Push to this iPhone from now on. 400 where the deployment has no APNs key."""
    await apns.register(current_user.id, device.token, session_id=session_id)


@router.delete("/apns/devices", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def unregister_iphone(
    current_user: CurrentUser,
    apns: ApnsSvc,
    token: str = Query(min_length=64, max_length=200, pattern=r"^[0-9a-f]+$"),
) -> None:
    """Stop pushing to this iPhone. 404 when it was not registered."""
    await apns.unregister(current_user.id, token)


@router.post("/test", response_model=PushTestRead)
async def send_test(
    current_user: CurrentUser, push: PushSvc, deployment: DeploymentSettingsSvc
) -> Any:
    """A push to every browser and iPhone of the caller's, to see that it
    arrives. 404 when none is subscribed."""
    outcome = await push.send_test(current_user.id, app_name=await deployment.effective_app_name())
    return PushTestRead(sent=outcome.sent, gone=outcome.gone, failed=outcome.failed)


@router.get("/preferences", response_model=PushPreferencesRead)
async def push_preferences(
    current_user: CurrentUser, session_id: CurrentSessionId, push: PushSvc
) -> Any:
    """This app sign-in's notification privacy and muted conversations."""
    return await push.preferences(current_user.id, session_id)


@router.put("/preferences", response_model=PushPreferencesRead)
async def set_push_preferences(
    data: PushPreferencesUpdate,
    current_user: CurrentUser,
    session_id: CurrentSessionId,
    push: PushSvc,
) -> Any:
    """Apply privacy and mute choices to this sign-in, including closed-app push."""
    return await push.set_preferences(current_user.id, session_id, data)


@router.put("/focus", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def push_focus(
    data: PushFocusUpdate, current_user: CurrentUser, session_id: CurrentSessionId, push: PushSvc
) -> None:
    """Suppress push to an open conversation for 90 seconds; clients renew while visible."""
    await push.focus(current_user.id, session_id, data.conversation_id)
