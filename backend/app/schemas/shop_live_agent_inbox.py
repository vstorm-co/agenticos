"""Live-agent inbox summary — queued threads (D3 B55)."""

from app.schemas.base import BaseSchema


class ShopLiveAgentInboxSummaryRead(BaseSchema):
    queued_widget_count: int
    queued_zalo_count: int
    queued_messenger_count: int
    queued_total: int
