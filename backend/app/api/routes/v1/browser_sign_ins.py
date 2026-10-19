"""Your saved browser sign-ins (#2129): which sites, and forgetting one.

There is no route that saves one. A sign-in is kept by its owner handing the
browser back with *keep me signed in* ticked, from the live view of a browse
acting as them - an agent's they took over, or one they opened here to sign in
to a site - the only moments the platform is holding a session they made
themselves. No route returns what one holds.

No `require(...)` gate: these are the caller's own, and the answer is the same
for a Viewer and an Owner.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import Auth, BrowserSignInSvc, CurrentUser
from app.schemas.browser_sign_in import (
    BrowserSignInList,
    SignInBrowserRead,
    SignInSessionCreate,
    SignInSessionRead,
)
from app.services import browser_sign_in_session

router = APIRouter()


@router.get("", response_model=BrowserSignInList)
async def my_sign_ins(service: BrowserSignInSvc, ctx: Auth) -> Any:
    """The sites the caller has kept a sign-in to in this organization."""
    items = await service.mine(ctx)
    return {"items": items, "total": len(items)}


@router.get("/browser", response_model=SignInBrowserRead)
async def sign_in_browser(ctx: Auth) -> Any:
    """Whether this deployment can open a browser to sign in to a site from Settings."""
    return {"available": browser_sign_in_session.available()}


@router.post("/sessions", response_model=SignInSessionRead, status_code=status.HTTP_201_CREATED)
async def sign_in_to_a_site(data: SignInSessionCreate, ctx: Auth, user: CurrentUser) -> Any:
    """Open a browser on a site for the caller to sign in to, held by them from the start.

    Watched and driven at the live view the answer names; handing it back with
    *keep me signed in* keeps the sign-in. Only the caller may see it.
    """
    return await browser_sign_in_session.begin(ctx, data.url, holder=user.full_name or user.email)


@router.delete("/{sign_in_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def forget_sign_in(sign_in_id: UUID, service: BrowserSignInSvc, ctx: Auth) -> None:
    """Forget one of the caller's sign-ins; a later browse starts signed out there."""
    await service.forget(ctx, sign_in_id)
