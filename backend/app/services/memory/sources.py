"""Reconcile typed, already authorized connector observations in the shared ledger."""

from dataclasses import dataclass
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.core.memory_keys import organization_owner_key
from app.db.models.memory_claim import MemoryClaim, MemoryMailEvent
from app.repositories import memory_claim
from app.schemas.base import BaseSchema
from app.schemas.memory import MemoryObjectRef, MemoryValue
from app.services.memory import _claims


class SourceObservation(BaseSchema):
    """The record an adapter produces after admission, before reconciliation.

    The provider-qualified stream key identifies revisions of one record. The
    external business key identifies the object across providers and chat.
    Delivery replay and grant validation remain the adapter's responsibility.
    Evidence is the minimal excerpt the adapter has authority to retain.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_key: str = Field(min_length=3, max_length=260, pattern=r"^[a-z][a-z0-9_]*:.+$")
    delivery_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=300)
    object: MemoryObjectRef
    subject: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=_claims.MAX_STATEMENT)
    value: MemoryValue | None
    effective_at: AwareDatetime


@dataclass(frozen=True)
class AppliedObservation:
    memory: _claims.Remembered
    previous: MemoryClaim | None = None
    late: bool = False


async def apply_observation(
    db: AsyncSession,
    *,
    organization_id: UUID,
    observation: SourceObservation,
    mail_event: MemoryMailEvent | None = None,
) -> AppliedObservation:
    """Apply one admitted record under the organization ledger's write lock.

    Adapters must carry durable evidence when access depends on a revocable grant.
    Gmail passes the locked event the worker independently reauthorized.
    """
    if mail_event is not None and (
        mail_event.organization_id != organization_id
        or mail_event.delivery_id != observation.delivery_id
        or mail_event.quote != observation.quote
        or mail_event.received_at != observation.effective_at
    ):
        raise BadRequestError(message="The observation does not match its admitted Gmail evidence")

    scope_key = organization_owner_key(organization_id)
    await _claims._hold_scope(db, organization_id=organization_id, scope_key=scope_key)
    ref = observation.object
    topic = _claims.normalise_subject(observation.subject)
    if topic is None:
        raise BadRequestError(message="An observation requires a normalized subject")

    # Legacy unbound Gmail rules keep their existing stream-specific identity.
    identity = f"external:{ref.external_key}" if ref.external_key else observation.source_key
    entity = await memory_claim.put_object(
        db,
        organization_id=organization_id,
        scope_key=scope_key,
        kind=ref.kind,
        name=ref.name,
        identity_key=identity,
    )
    scope = memory_claim.ClaimScope(scope_key)
    previous = await memory_claim.about_subject(
        db,
        organization_id=organization_id,
        scope=scope,
        subject=topic,
        object_id=entity.id,
        statuses=("current", "disputed", "superseded"),
        lock=True,
    )
    effective = observation.effective_at
    candidates = [claim for claim in previous if _claims.covers(claim, effective)]
    for claim in reversed(candidates):
        if (
            claim.kind == "fact"
            and claim.episode is None
            and _claims.same_observation(claim, observation.value, observation.statement)
        ):
            _attach(mail_event, claim, observation)
            return AppliedObservation(
                _claims.Remembered(claim, created=False, disputed=claim.status == "disputed")
            )

    def same_stream(claim: MemoryClaim) -> bool:
        return claim.origin == "agent" and (
            claim.observation_source == observation.source_key
            or (
                claim.observation_source is None
                and claim.mail_event_id is not None
                and identity == observation.source_key
            )
        )

    late = any(
        claim.effective_from is not None and claim.effective_from > effective for claim in previous
    )
    live = [claim for claim in candidates if claim.status in ("current", "disputed")]
    active = live[0] if len(live) == 1 and live[0].status == "current" else None
    advance = (
        not late
        and active is not None
        and same_stream(active)
        and active.effective_from is not None
        and active.effective_from < effective
    )
    # An out-of-order revision can split the history of its own stream.
    # Independent and tied observations must go through the normal dispute rules.
    if late:
        for claim in candidates:
            if (
                same_stream(claim)
                and claim.effective_to is not None
                and claim.effective_from is not None
                and claim.effective_from < effective
            ):
                await memory_claim.set_status(db, claim, "superseded", effective_to=effective)
    stored = await _claims.remember(
        db,
        organization_id=organization_id,
        scope=scope,
        object_id=entity.id,
        statement=observation.statement,
        subject=topic,
        effective_from=effective,
        mail_event_id=mail_event.id if mail_event is not None else None,
        value=observation.value,
        observation_source=observation.source_key,
        corrects=advance,
    )
    _attach(mail_event, stored.claim, observation)
    return AppliedObservation(stored, previous=active if advance else None, late=late)


def _attach(
    event: MemoryMailEvent | None, claim: MemoryClaim, observation: SourceObservation
) -> None:
    if event is not None:
        event.supported_claim_id = claim.id
        event.claim_statement = observation.statement
        event.observation_source = observation.source_key
