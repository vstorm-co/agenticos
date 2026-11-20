"""Closed owner summaries and bounded pagination; discovery never performs a transition."""

import base64
import binascii
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime

from app.core.browser_procedure_teaching import (
    BrowserProcedureTeachingGeneration,
    BrowserProcedureTeachingModel,
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingState,
)
from app.core.field_errors import refused_field
from app.db.models.browser_procedure_teaching import BrowserProcedureTeachingSession
from app.schemas.browser_procedure_teaching import BrowserProcedureTeachingSummary

MAX_CURSOR_LENGTH = 512
MAX_PAGE_SIZE = 100


class _Cursor(BrowserProcedureTeachingModel):
    version: Literal[1]
    organization_id: UUID
    owner_user_id: UUID
    created_at: AwareDatetime
    id: UUID


def _encode(cursor: _Cursor) -> str:
    return base64.urlsafe_b64encode(cursor.model_dump_json().encode()).decode().rstrip("=")


def encode_cursor(
    organization_id: UUID, owner_user_id: UUID, row: BrowserProcedureTeachingSession
) -> str:
    return _encode(
        _Cursor(
            version=1,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            created_at=row.created_at,
            id=row.id,
        )
    )


def decode_cursor(value: str, organization_id: UUID, owner_user_id: UUID) -> tuple[datetime, UUID]:
    """A cursor narrows a SQL-scoped owner page; it never grants access to a row."""
    refusal = refused_field(
        "cursor", "Invalid browser teaching cursor", reason_code="invalid_cursor"
    )
    if not value or len(value) > MAX_CURSOR_LENGTH:
        raise refusal
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        cursor = _Cursor.model_validate_json(raw)
    except ValueError, binascii.Error:
        raise refusal from None
    if (
        _encode(cursor) != value
        or cursor.organization_id != organization_id
        or cursor.owner_user_id != owner_user_id
    ):
        raise refusal
    return cursor.created_at, cursor.id


def expired(status: str, expires_at: datetime, now: datetime) -> bool:
    """The same retention boundary is used by discovery and canonical owner reads."""
    return (
        status
        in {
            BrowserProcedureTeachingState.RECORDING,
            BrowserProcedureTeachingState.PAUSED,
            BrowserProcedureTeachingState.REVIEW,
        }
        and expires_at <= now
    )


def summary(row: BrowserProcedureTeachingSession, now: datetime) -> BrowserProcedureTeachingSummary:
    data = BrowserProcedureTeachingSummary.model_validate(row, from_attributes=True)
    if not expired(row.status, row.expires_at, now):
        return data
    return data.model_copy(
        update={
            "title": "",
            "allowed_origins": (),
            "status": BrowserProcedureTeachingState.EXPIRED,
            "reason_code": BrowserProcedureTeachingReason.EXPIRED,
            "revision": row.revision + 1,
            "generation_state": (
                BrowserProcedureTeachingGeneration.CANCELLED
                if data.generation_state
                in {
                    BrowserProcedureTeachingGeneration.QUEUED,
                    BrowserProcedureTeachingGeneration.GENERATING,
                }
                else data.generation_state
            ),
        }
    )
