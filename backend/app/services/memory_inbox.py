"""Deliver approved memory policy decisions through the existing notification center."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.notification import NotificationChannel, NotificationEventType
from app.repositories import memory_claim
from app.schemas.memory import MemoryInboxContext
from app.services.memory_inbox_policy import (
    POLICY_VERSION,
    authorized_inbox_source,
    current_inbox_scopes,
    inbox_evidence,
    pending_change,
)
from app.services.notification_center import NotificationCenterService
from app.worker.jobs import DeliverMemoryInbox


async def deliver_memory_inbox(db: AsyncSession, payload: DeliverMemoryInbox) -> int:
    """Settle a durable notification attempt, with current source and audience access."""
    if payload.policy_version != POLICY_VERSION:
        return 0
    rule = await memory_claim.inbox_rule(
        db,
        organization_id=payload.organization_id,
        for_delivery=True,
    )
    if rule is None or rule.version != payload.rule_version or rule.mode == "off":
        return 0
    rows = await memory_claim.many(
        db,
        organization_id=payload.organization_id,
        claim_ids=[payload.claim_id, payload.previous_id],
    )
    evidence = inbox_evidence(
        {row.id: row for row in rows},
        claim_id=payload.claim_id,
        previous_id=payload.previous_id,
    )
    if evidence is None:
        return 0
    claim, previous = evidence
    if not pending_change(payload, claim, previous, now=datetime.now(UTC)):
        return 0
    if await memory_claim.latest_claim_revision(db, claim_id=claim.id) != payload.revision_at:
        return 0
    context = MemoryInboxContext(
        claim_id=claim.id,
        previous_id=previous.id,
        change=payload.change,
        source=payload.source,
        source_event_id=payload.source_event_id,
    )
    events = await memory_claim.readable_event_ids(
        db,
        organization_id=payload.organization_id,
        event_ids={context.source_event_id} if context.source_event_id is not None else set(),
    )
    if payload.source not in rule.sources or not authorized_inbox_source(
        claim, context, events=events
    ):
        return 0
    assert claim.object_id is not None  # A pending change belongs to an object.
    entity = await memory_claim.get_object(
        db,
        organization_id=payload.organization_id,
        object_id=claim.object_id,
        scope_keys=[claim.scope_key],
    )
    if entity is None or entity.kind != "commitment":
        return 0

    center = NotificationCenterService(db)
    delivered = 0
    for recipient_id in sorted(rule.recipient_ids):
        scopes = await current_inbox_scopes(
            db,
            organization_id=payload.organization_id,
            user_id=recipient_id,
        )
        if claim.scope_key not in scopes:
            continue
        receipt = await memory_claim.record_inbox_decision(
            db,
            organization_id=payload.organization_id,
            claim_id=claim.id,
            rule_version=payload.rule_version,
            policy_version=payload.policy_version,
            revision_at=payload.revision_at,
            recipient_id=recipient_id,
            change=payload.change,
            outcome="shadow" if rule.mode == "shadow" else "muted",
        )
        if receipt is None or rule.mode == "shadow":
            continue
        rows = await center.write(
            organization_id=payload.organization_id,
            recipients=[recipient_id],
            event_type=NotificationEventType.MEMORY_DEADLINE_CHANGE,
            occurrence_id=(
                f"{claim.id}:{payload.revision_at.isoformat()}:"
                f"{payload.policy_version}:{payload.rule_version}:{payload.change}"
            ),
            summary="A shared commitment deadline changed",
            context_url=f"/settings/memory?library=organization&object={entity.id}",
            render_context=context.model_dump(mode="json"),
            channels={NotificationChannel.IN_APP},
        )
        if rows and rows[0].in_app_visible:
            receipt.outcome = "delivered"
            delivered += 1
    await db.flush()
    return delivered
