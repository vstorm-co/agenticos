"""Explicit consent and receipts; no cookies, browser output or destination URL input."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.browser_continuation import BrowserContinuationReason, BrowserContinuationState


class BrowserCredentialContinuationRequest(BaseModel):
    """The request UUID is the receipt id; preparation alone authorizes no effect."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    request_id: UUID


class BrowserCredentialContinuationConfirmation(BaseModel):
    """One immutable decision for the exact current document and credential generation."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    document_id: UUID
    authorization_generation: UUID
    approve: bool
    keep_signed_in: bool


class BrowserCredentialContinuationRead(BaseModel):
    """Continued means a protected context exists; it does not assert authentication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    organization_id: UUID
    user_id: UUID
    run_id: UUID
    source_submission_id: UUID
    source_fill_id: UUID
    source_call_id: str = Field(min_length=1, max_length=200)
    source_tab_id: str = Field(min_length=1, max_length=200)
    secret_id: UUID
    authorization_generation: UUID
    state: BrowserContinuationState
    origin: str | None
    document_id: UUID | None
    expires_at: datetime
    keep_signed_in: bool | None
    saved_sign_in_id: UUID | None
    continuation_call_id: str | None = Field(min_length=1, max_length=200)
    continuation_tab_id: str | None = Field(min_length=1, max_length=200)
    reason_code: BrowserContinuationReason | None
    output_protected: Literal[True] = True
