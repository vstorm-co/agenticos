"""Browser credential selection and confirmation contain references, never values."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.browser_fill import (
    BrowserFillField,
    BrowserFillOperation,
    BrowserFillReason,
    BrowserFillSelection,
    BrowserFillState,
)
from app.schemas.secret import BrowserSecretMetadata


class BrowserCredentialEligible(BaseModel):
    id: UUID
    name: str
    kind: Literal["browser_login", "browser_profile"]
    authorization_generation: UUID
    usage_scope: Literal["personal", "organization"]
    browser: BrowserSecretMetadata


class BrowserCredentialRequest(BrowserFillSelection):
    """A caller proposes existing handles; only the live controller observes them."""

    request_id: UUID
    secret_id: UUID
    authorization_generation: UUID
    call_id: str = Field(min_length=1, max_length=200)
    tab_id: str = Field(min_length=1, max_length=200)


class BrowserCredentialConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: UUID
    authorization_generation: UUID
    approve: bool


class BrowserCredentialSubmission(BaseModel):
    """A new explicit action tied to the exact successfully filled document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    document_id: UUID
    authorization_generation: UUID


class BrowserCredentialPlanRead(BaseModel):
    id: UUID
    operation: BrowserFillOperation
    parent_plan_id: UUID | None
    run_id: UUID
    call_id: str
    tab_id: str
    secret_id: UUID
    authorization_generation: UUID
    state: BrowserFillState
    fields: list[BrowserFillField]
    origin: str | None
    document_id: UUID | None
    expires_at: datetime
    submission_expires_at: datetime | None = None
    reason_code: BrowserFillReason | None
    output_protected: bool


class BrowserCredentialPolicyWrite(BaseModel):
    """An explicit scope transition; generic sharing cannot transfer a credential."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    generation: UUID
    mode: Literal["personal", "shared"]
    agent_ids: tuple[UUID, ...] = Field(default=(), max_length=50)
    member_ids: tuple[UUID, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def _explicit_shared_audience(self) -> BrowserCredentialPolicyWrite:
        if self.mode == "shared" and (not self.agent_ids or not self.member_ids):
            raise ValueError("Shared browser use requires named agents and members")
        if self.mode == "personal" and (self.agent_ids or self.member_ids):
            raise ValueError("Personal browser use cannot retain shared grants")
        if len(set(self.agent_ids)) != len(self.agent_ids) or len(set(self.member_ids)) != len(
            self.member_ids
        ):
            raise ValueError("Each agent and member may be named only once")
        return self


class BrowserCredentialPolicyRead(BaseModel):
    secret_id: UUID
    authorization_generation: UUID
    mode: Literal["personal", "shared"]
    agent_ids: list[UUID]
    member_ids: list[UUID]
