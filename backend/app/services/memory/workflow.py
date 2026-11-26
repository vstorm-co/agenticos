"""Write typed memory through a published workflow's existing delivery authority."""

import hashlib
import json
import re
from datetime import UTC, date, datetime
from email.utils import parseaddr
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.memory_keys import organization_owner_key
from app.core.permissions import AuthContext, Perm, Scope
from app.db.models.memory_claim import MemoryMailEvent
from app.db.models.workflow_exposure import WorkflowWebhookDelivery
from app.db.models.workflow_run import WorkflowRun, WorkflowRunMode, WorkflowRunTrigger
from app.repositories import mcp_connection_repo, memory_claim, workflow_exposure, workflow_run
from app.schemas.memory import MemoryObjectKind, MemoryObjectRef, MemoryValue
from app.services.memory import _claims
from app.services.memory.sources import SourceObservation, apply_observation
from app.workflows.nodes._triggers import EmailTriggerOutput, WebhookTriggerOutput

_DEADLINE_LINE = re.compile(r"^Deadline:[ \t]{1,12}(\d{4}-\d{2}-\d{2}|cancelled)[ \t]{0,12}$", re.M)


class MemoryObservationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_kind: MemoryObjectKind
    object_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
    ]
    object_key: str = Field(
        min_length=1, max_length=260, description="External business object key."
    )
    subject: str = Field(
        min_length=1, max_length=120, description="Business property. Use deadline for Gmail."
    )

    @field_validator("subject")
    @classmethod
    def _property(cls, value: str) -> str:
        topic = _claims.normalise_subject(value)
        if topic is None:
            raise ValueError("Choose a valid business property")
        return topic


class SignedObservation(BaseModel):
    """A signed CRM relay may deliver exactly these fields to the workflow."""

    model_config = ConfigDict(extra="forbid")

    record_key: str = Field(min_length=1, max_length=260)
    object_key: str = Field(min_length=1, max_length=260)
    subject: str = Field(min_length=1, max_length=120)
    value: MemoryValue | None
    quote: str = Field(min_length=1, max_length=300)
    effective_at: AwareDatetime


class MemoryObservationOutput(BaseModel):
    status: Literal["preview", "applied", "changed", "duplicate", "disputed", "late"]
    changed: bool = False
    claim_id: UUID | None = None


def require_editor(auth: AuthContext) -> None:
    if (
        auth.key_scopes is not None
        or auth.subject_is_publisher_fallback
        or auth.scope_for(Perm.CONTEXT_EDIT) != Scope.ALL
    ):
        raise AuthorizationError(
            message="Writing company memory requires organization-wide context:edit"
        )


def _gmail(run: WorkflowRun) -> tuple[MemoryValue | None, str, datetime, str]:
    email = EmailTriggerOutput.model_validate(run.input)
    lines = list(_DEADLINE_LINE.finditer(email.text.replace("\r\n", "\n")))
    if len(lines) != 1 or email.received_at is None or email.received_at.tzinfo is None:
        raise BadRequestError(
            message="Gmail memory requires one dated Deadline line or a cancellation"
        )
    row = lines[0]
    value = row.group(1)
    return (
        None if value == "cancelled" else date.fromisoformat(value).isoformat(),
        row.group(0),
        email.received_at,
        f"{parseaddr(email.sender)[1].casefold()}/{email.subject}",
    )


async def _delivery(
    db: AsyncSession, run: WorkflowRun
) -> tuple[WorkflowRun, WorkflowWebhookDelivery]:
    # A manual retry hands on the original input, but has no delivery of its own.
    original = run
    while original.retry_of_run_id is not None:
        earlier = await workflow_run.get_run(
            db, original.retry_of_run_id, organization_id=run.organization_id
        )
        if earlier is None or earlier.workflow_id != run.workflow_id:
            raise BadRequestError(message="The workflow's original delivery is unavailable")
        original = earlier
    receipt = await workflow_exposure.delivery_for_run(
        db, organization_id=run.organization_id, run_id=original.id
    )
    if receipt is None:
        raise BadRequestError(
            message="Memory requires an admitted Gmail or signed webhook delivery"
        )
    return original, receipt


async def record_observation(
    db: AsyncSession,
    *,
    auth: AuthContext,
    run_id: UUID,
    config: MemoryObservationConfig,
) -> MemoryObservationOutput:
    """Resolve trusted inputs, update the ledger, and persist the result in one transaction."""
    require_editor(auth)
    run = await workflow_run.get_run(db, run_id, organization_id=auth.organization_id)
    if run is None or run.impersonated:
        raise AuthorizationError(message="No authorized workflow run for this memory write")
    if run.mode == WorkflowRunMode.TEST:
        return MemoryObservationOutput(status="preview")

    topic = config.subject
    ref = MemoryObjectRef(
        kind=config.object_kind, name=config.object_name, external_key=config.object_key
    )
    run, receipt = await _delivery(db, run)
    try:
        if run.triggered_by == WorkflowRunTrigger.GMAIL:
            grant_id = receipt.portal_grant_id
            generation = receipt.portal_authorization_generation
            if grant_id is None or generation is None or topic != "deadline":
                raise AuthorizationError(
                    message="Use a Gmail trigger with a full authenticated sender address and the deadline property"
                )
            grant = await mcp_connection_repo.get_by_id_for_update(db, grant_id)
            if (
                grant is None
                or grant.organization_id != run.organization_id
                or grant.purpose != "portal"
                or grant.portal_key != "google"
                or grant.authorization_generation != generation
                or not grant.is_enabled
                or grant.oauth_payload is None
                or grant.authorization_expired
            ):
                raise AuthorizationError(
                    message="The original Gmail mailbox grant is no longer authorized"
                )
            value, quote, effective, record = _gmail(run)
            provider = "gmail"
        elif run.triggered_by == WorkflowRunTrigger.WEBHOOK and receipt.signed_digest:
            delivery = WebhookTriggerOutput.model_validate(run.input)
            observation = SignedObservation.model_validate(delivery.body)
            if observation.object_key != ref.external_key or observation.subject != topic:
                raise BadRequestError(
                    message="The webhook observation does not match the reviewed object and property"
                )
            value, quote, effective, record = (
                observation.value,
                observation.quote,
                observation.effective_at,
                observation.record_key,
            )
            assert run.workflow_version_id is not None  # A real workflow is pinned.
            grant_id, generation, provider = receipt.exposure_id, run.workflow_version_id, "webhook"
        else:
            raise AuthorizationError(
                message="This workflow entry cannot write external observations"
            )
    except (ValidationError, ValueError) as error:
        raise BadRequestError(
            message="The admitted delivery has an invalid memory observation"
        ) from error
    if effective > datetime.now(UTC):
        raise BadRequestError(message="An external observation cannot begin in the future")

    # Follow the poller's grant-before-exposure lock order and fence a pause or
    # republish until the effect has committed.
    exposure = await workflow_exposure.get(
        db,
        receipt.exposure_id,
        organization_id=run.organization_id,
        workflow_id=run.workflow_id,
        for_update=True,
    )
    if (
        exposure is None
        or not exposure.is_active
        or exposure.workflow_version_id != run.workflow_version_id
    ):
        raise AuthorizationError(message="The workflow's approved trigger is no longer active")

    identity = (
        str(grant_id),
        ref.kind,
        ref.external_key,
        topic,
        str(generation) if provider == "gmail" else None,
    )
    source_key = (
        provider + ":" + hashlib.sha256(json.dumps([identity, record]).encode()).hexdigest()
    )
    event_key = (
        "workflow:"
        + hashlib.sha256(json.dumps([identity, receipt.delivery_id]).encode()).hexdigest()
    )
    organization_id = run.organization_id
    await _claims._hold_scope(
        db, organization_id=organization_id, scope_key=organization_owner_key(organization_id)
    )
    existing = await memory_claim.workflow_evidence(
        db, organization_id=organization_id, grant_id=grant_id, event_key=event_key
    )
    if existing is not None:
        if existing.workflow_delivery_id != receipt.id:
            return MemoryObservationOutput(status="duplicate", claim_id=existing.supported_claim_id)
        return MemoryObservationOutput.model_validate(
            {
                "status": existing.state,
                "changed": existing.state == "changed",
                "claim_id": existing.supported_claim_id,
            }
        )

    event = MemoryMailEvent(
        organization_id=organization_id,
        grant_id=grant_id,
        generation=generation,
        delivery_id=event_key,
        received_at=effective,
        quote=quote,
        workflow_delivery_id=receipt.id,
        provider=provider,
        state="queued",
    )
    db.add(event)
    await db.flush()
    statement = (
        f"{ref.name} deadline cancelled"
        if provider == "gmail" and value is None
        else f"{ref.name} {topic.replace('_', ' ')}: {value}"
    )
    result = await apply_observation(
        db,
        organization_id=organization_id,
        mail_event=event,
        observation=SourceObservation(
            source_key=source_key,
            delivery_id=event_key,
            quote=quote,
            object=ref,
            subject=topic,
            statement=statement,
            value=value,
            effective_at=effective,
        ),
    )
    memory = result.memory
    status: Literal["applied", "changed", "duplicate", "disputed", "late"] = (
        "duplicate"
        if not memory.created
        else "disputed"
        if memory.disputed
        else "late"
        if result.late
        else "changed"
        if result.previous is not None
        else "applied"
    )
    event.state = status
    return MemoryObservationOutput(
        status=status, changed=status == "changed", claim_id=memory.claim.id
    )
