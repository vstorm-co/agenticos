"""Your saved browser sign-ins (#2129): which sites, and forgetting one.

There is no route that saves one. A sign-in is kept by its owner handing the
browser back with *keep me signed in* ticked, from the live view of a browse
acting as them - the only moment the platform is holding a session they made
themselves. No route returns what one holds.

No `require(...)` gate: these are the caller's own, and the answer is the same
for a Viewer and an Owner.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import Auth, BrowserSignInSvc
from app.schemas.browser_sign_in import BrowserSignInList

router = APIRouter()


@router.get("", response_model=BrowserSignInList)
async def my_sign_ins(service: BrowserSignInSvc, ctx: Auth) -> Any:
    """The sites the caller has kept a sign-in to in this organization."""
    items = await service.mine(ctx)
    return {"items": items, "total": len(items)}


@router.delete("/{sign_in_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def forget_sign_in(sign_in_id: UUID, service: BrowserSignInSvc, ctx: Auth) -> None:
    """Forget one of the caller's sign-ins; a later browse starts signed out there."""
    await service.forget(ctx, sign_in_id)
