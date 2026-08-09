"""Claiming a chat account for the signed-in person.

Under `/me` because that is exactly what authorises it: the URL arrived in a chat
and says which account is on offer, and the session says who is accepting. Only
the second of those can be trusted, which is why the confirmation happens here
and not in the chat.
"""

from typing import Any

from fastapi import APIRouter

from app.api.deps import ChannelLinkSvc, CurrentUser
from app.core.exceptions import NotFoundError
from app.schemas.channel_bot import ChannelLinkRequestRead

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
