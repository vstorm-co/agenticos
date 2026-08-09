"""Connecting the current user's chat accounts to their account here.

Under `/me` because a link code names one person and nobody else may mint one for
them: the code is a bearer credential for the duration of its life, and whoever
types it into a chat becomes that account as far as every channel is concerned.
"""

from typing import Any

from fastapi import APIRouter, status

from app.api.deps import ChannelLinkSvc, CurrentUser
from app.schemas.channel_bot import ChannelLinkCodeRead

router = APIRouter()


@router.post("", response_model=ChannelLinkCodeRead, status_code=status.HTTP_201_CREATED)
async def mint_link_code(service: ChannelLinkSvc, user: CurrentUser) -> Any:
    """Issue a code to type at a bot, replacing any this user already holds.

    A POST rather than a GET, and it is not idempotent on purpose: asking again
    is how somebody replaces a code they lost, and the one they lost stops
    working the moment they do.
    """
    return await service.mint(user.id)
