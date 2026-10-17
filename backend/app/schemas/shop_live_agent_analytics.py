"""Live-agent analytics report (D3 B55)."""

from app.schemas.base import BaseSchema


class ShopLiveAgentAnalyticsReportRead(BaseSchema):
    period_days: int
    queued_total: int
    human_active_total: int
    sessions_claimed: int
    staff_reply_count: int
    avg_first_response_seconds: float | None = None
    median_first_response_seconds: float | None = None
    samples_first_response: int = 0
