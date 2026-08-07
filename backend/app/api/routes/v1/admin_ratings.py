from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import CurrentAppAdmin, MessageRatingSvc, StreamingMessageRatingSvc
from app.schemas.message_rating import MessageRatingList, RatingSummary

router = APIRouter()


@router.get("", response_model=MessageRatingList)
async def list_ratings_admin(
    rating_service: MessageRatingSvc,
    _: CurrentAppAdmin,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    rating_filter: int | None = Query(None, ge=-1, le=1, description="Filter by rating value"),
    with_comments_only: bool = Query(False, description="Only show ratings with comments"),
) -> Any:
    """List all ratings with filtering (admin only)."""
    items, total = await rating_service.list_ratings(
        skip=skip,
        limit=limit,
        rating_filter=rating_filter,
        with_comments_only=with_comments_only,
    )
    return MessageRatingList(items=items, total=total)


@router.get("/summary", response_model=RatingSummary)
async def get_rating_summary(
    rating_service: MessageRatingSvc,
    _: CurrentAppAdmin,
    from_: date | None = Query(None, alias="from", description="First day, inclusive (UTC)"),
    to: date | None = Query(None, description="Last day, inclusive (UTC)"),
) -> Any:
    """Get aggregated rating statistics (admin only).

    The window is spelled the way `GET /stats/ratings/summary` spells it, so
    the dashboard's period filter reaches the deployment-wide card as well as
    the organization's. Omitting both dates means the last thirty days.
    """
    return await rating_service.get_summary(from_date=from_, to_date=to)


@router.get("/export", response_model=None)
async def export_ratings(
    rating_service: StreamingMessageRatingSvc,
    _: CurrentAppAdmin,
    export_format: Literal["json", "csv"] = Query("json", description="Export format"),
    rating_filter: int | None = Query(None, ge=-1, le=1, description="Filter by rating value"),
    with_comments_only: bool = Query(False, description="Only show ratings with comments"),
) -> Any:
    """Export all ratings as JSON or CSV (admin only).

    CSV is streamed row-by-row; JSON collects into a single document.

    The one endpoint on a `StreamingDBSession`: the CSV generator reads its next
    page after the response has started, which an ordinary `DBSession` has
    already committed and closed by. It reads and never writes, so nothing here
    depends on the acknowledgement ordering #353 is about.
    """
    result = await rating_service.export_ratings(
        export_format=export_format,
        rating_filter=rating_filter,
        with_comments_only=with_comments_only,
    )
    if result.media_type == "text/csv":
        return StreamingResponse(
            result.payload,
            media_type="text/csv",
            headers={"Content-Disposition": result.content_disposition},
        )
    return JSONResponse(
        content=result.payload,
        headers={"Content-Disposition": result.content_disposition},
    )
