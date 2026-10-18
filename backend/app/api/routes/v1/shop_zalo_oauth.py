"""Public Zalo OA OAuth callback (browser redirect from Zalo)."""

from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

from app.api.deps import DBSession
from app.services.shop_zalo_oauth_flow import handle_shop_zalo_oauth_callback

router = APIRouter(prefix="/shop-oauth/zalo")


@router.get("/callback")
async def zalo_oauth_callback(
    db: DBSession,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    oa_id: Annotated[str | None, Query(alias="oa_id")] = None,
) -> Any:
    target = await handle_shop_zalo_oauth_callback(db, code=code, state=state, oa_id=oa_id)
    return RedirectResponse(url=target, status_code=302)
