"""Where the organization's browses run: built in, through a proxy, or a hosted browser (#2130).

Gated like the other places agents run - sandbox hosts - on `connections:*`: the
setting decides where every browse in the organization sends its traffic.
"""

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import Auth, BrowserSettingSvc, require
from app.core.permissions import Perm
from app.schemas.browser_setting import BrowserSettingRead, BrowserSettingUpdate

router = APIRouter()


@router.get(
    "",
    response_model=BrowserSettingRead,
    dependencies=[Depends(require(Perm.CONNECTIONS_VIEW))],
)
async def read_browser_setting(service: BrowserSettingSvc, ctx: Auth) -> Any:
    """The organization's browser setting - the default when it never set one."""
    return await service.get(ctx)


@router.put(
    "",
    response_model=BrowserSettingRead,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def update_browser_setting(
    data: BrowserSettingUpdate, service: BrowserSettingSvc, ctx: Auth
) -> Any:
    """Write the whole setting; the next browse in the organization uses it."""
    return await service.update(ctx, data)
