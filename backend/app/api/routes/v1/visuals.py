"""The visuals an agent drew for the caller, as the dashboard lists them (#2171)."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.deps import Auth, VisualSvc
from app.api.routes.v1._artifact_bytes import visual_image_response
from app.schemas.visual import VisualList

router = APIRouter()


@router.get("", response_model=VisualList)
async def list_recent_visuals(
    service: VisualSvc,
    ctx: Auth,
    limit: int = Query(8, ge=1, le=24, description="How many, newest first"),
) -> Any:
    """The caller's latest drawings in this organization - titles and where, never content."""
    return await service.recent(ctx, limit=limit)


@router.get("/{visual_id}/thumbnail", response_class=Response)
async def get_visual_thumbnail(visual_id: UUID, service: VisualSvc, ctx: Auth) -> Response:
    """A drawing's thumbnail, for the person it was drawn for."""
    return visual_image_response(await service.thumbnail(ctx, visual_id), "image/png")
