"""What the signed-in person watches in their own connections (#2301).

Under `/me`, like suggestions: a watch reads one person's own account and what
it finds is theirs alone, so there is no view of anybody else's.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import Auth, WatchSvc
from app.schemas.watch import (
    WatchCreate,
    WatchList,
    WatchPresetList,
    WatchPresetRead,
    WatchRead,
    WatchUpdate,
)

router = APIRouter()


@router.get("", response_model=WatchList)
async def list_my_watches(service: WatchSvc, ctx: Auth) -> Any:
    """The person's watches here, and why any that is on is not being read."""
    items = await service.list_mine(ctx)
    return WatchList(items=items, total=len(items))


@router.get("/presets", response_model=WatchPresetList)
async def list_watch_presets(service: WatchSvc, ctx: Auth) -> Any:
    """Ready-made watches, by the catalog server each is for."""
    items = [
        WatchPresetRead(
            key=preset.key,
            server=preset.catalog_key,
            instructions=preset.instructions,
            interval_minutes=preset.interval_minutes,
            urgent=preset.urgent,
        )
        for preset in service.presets()
    ]
    return WatchPresetList(items=items, total=len(items))


@router.post("", response_model=WatchRead, status_code=status.HTTP_201_CREATED)
async def create_watch(data: WatchCreate, service: WatchSvc, ctx: Auth) -> Any:
    """Watch one of the person's own connections; the first look is within a minute."""
    return await service.create(ctx, data)


@router.patch("/{watch_id}", response_model=WatchRead)
async def update_watch(watch_id: UUID, data: WatchUpdate, service: WatchSvc, ctx: Auth) -> Any:
    """Change what it looks for, how often, what to leave out, or switch it off."""
    return await service.update(ctx, watch_id, data)


@router.delete("/{watch_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_watch(watch_id: UUID, service: WatchSvc, ctx: Auth) -> None:
    """Stop watching, and drop what it found."""
    await service.delete(ctx, watch_id)
