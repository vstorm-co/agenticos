"""Shop KB delete with content transfer (D3 B60)."""

from app.schemas.base import BaseSchema


class ShopKbDeleteResult(BaseSchema):
    faq_entries_transferred: int = 0
    faq_entries_skipped_duplicate: int = 0
    suggestions_transferred: int = 0
    suggestions_merged: int = 0
    documents_transferred: int = 0
    documents_skipped: int = 0
