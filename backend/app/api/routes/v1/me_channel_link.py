"""Claiming a chat account for the signed-in person.

Under `/me` because that is exactly what authorises it: the URL arrived in a chat
and says which account is on offer, and the session says who is accepting. Only
the second of those can be trusted, which is why the confirmation happens here
and not in the chat.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import ChannelLinkSvc, CurrentUser
from app.core.exceptions import NotFoundError
from app.schemas.channel_bot import (
    ChannelIdentityList,
    ChannelIdentityRead,
    ChannelLinkRequestRead,
)

router = APIRouter()

_GONE = "This link is not valid any more. Send the bot a message to get a new one."


@router.get("/{token}", response_model=ChannelLinkRequestRead)
async def read_link_request(token: str, service: ChannelLinkSvc, user: CurrentUser) -> Any:
    """Which chat account this URL is about, so the page can name it."""
    request = await service.pending(token)
    if request is None:
        raise NotFoundError(message=_GONE)
    return request


@router.post("/{token}", response_model=ChannelLinkRequestRead)
async def confirm_link_request(token: str, service: ChannelLinkSvc, user: CurrentUser) -> Any:
    """Attach that chat account to the caller, and spend the link.

    Rechecked rather than trusting the GET that preceded it: the two are separate
    requests, and a token can expire or be spent between them.
    """
    request = await service.confirm(token, user.id)
    if request is None:
        raise NotFoundError(message=_GONE)
    return request


@router.get("", response_model=ChannelIdentityList)
async def list_linked_accounts(service: ChannelLinkSvc, user: CurrentUser) -> Any:
    """The chat accounts this person has connected.

    Worth a page of its own rather than only a confirmation screen: a link is
    granted from a chat and spent in a browser, so without a list the only
    record of what somebody connected is a message that has scrolled away.
    """
    items = await service.linked(user.id)
    return ChannelIdentityList(
        items=[ChannelIdentityRead.model_validate(identity) for identity in items],
        total=len(items),
    )


@router.delete("/{identity_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def unlink_account(identity_id: UUID, service: ChannelLinkSvc, user: CurrentUser) -> None:
    """Disconnect one chat account from this person."""
    if not await service.unlink(user.id, identity_id):
        raise NotFoundError(message="That chat account is not connected to your account.")
