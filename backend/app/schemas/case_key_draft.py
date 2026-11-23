"""Keys drafted from a case's reference answer, as the API shows them."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema
from app.schemas.scoring import DocumentKey


class ExtractedKeys(BaseSchema):
    """What the key extractor answers: every fact the document states."""

    keys: list[DocumentKey] = Field(default_factory=list)


class CaseKeyDraftRead(BaseSchema):
    """The keys drafted for one case, still being drafted, or why they could not be.

    `keys` holds only the facts whose value the reference answer states as
    written; a person reviews them before they become the case's keys check.
    """

    id: UUID
    case_id: UUID
    status: Literal["running", "ready", "failed"]
    keys: list[DocumentKey]
    error: str | None
    created_at: datetime
    finished_at: datetime | None
