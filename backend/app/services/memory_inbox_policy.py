"""Versioned, deterministic admission and current access for memory Inbox cards."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory_keys import GROUP_PREFIX, group_owner_key, organization_owner_key
from app.core.permissions import AuthContext, Perm
from app.db.models.memory_claim import MemoryClaim
from app.repositories import group_repo, memory_claim
from app.repositories import member as member_repo
from app.schemas.memory import MemoryInboxChange, MemoryInboxContext, MemoryInboxSource
from app.services.background_jobs import enqueue
from app.worker.jobs import DELIVER_MEMORY_INBOX, SHADOW_MEMORY_INBOX, DeliverMemoryInbox

POLICY_VERSION = 1
_CONNECTOR_SOURCES: dict[str, MemoryInboxSource] = {"gmail": "gmail", "webhook": "webhook"}
_CHANGE_LABELS = {
    "changed": "commitment deadline changed",
    "cancelled": "commitment deadline cancelled",
    "review": "commitment deadline needs review",
}


@dataclass(frozen=True)
class InboxWording:
    summary: str
    params: dict[str, str]


def _deadline(value: str | int | bool | None) -> str | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        canonical = date.fromisoformat(value).isoformat()
    except ValueError:
        return None
    return canonical if value == canonical else None


def _shared(claim: MemoryClaim) -> bool:
    return claim.agent_id is None and (
        claim.scope_key == organization_owner_key(claim.organization_id)
        or claim.scope_key.startswith(GROUP_PREFIX)
    )


def _commitment_property(claim: MemoryClaim) -> bool:
    return (
        _shared(claim)
        and claim.object_id is not None
        and claim.subject == "deadline"
        and claim.kind == "fact"
        and claim.episode is None
    )


def _change(
    claim: MemoryClaim,
    previous: MemoryClaim,
    *,
    review: bool,
) -> MemoryInboxChange | None:
    if not _commitment_property(claim) or (
        claim.id == previous.id
        or claim.organization_id != previous.organization_id
        or claim.object_id != previous.object_id
        or claim.scope_key != previous.scope_key
        or claim.agent_id != previous.agent_id
        or previous.subject != claim.subject
    ):
        return None
    before, after = _deadline(previous.value), _deadline(claim.value)
    # A missing value on an untyped chat claim isn't evidence of a cancellation.
    cancelled = before is not None and claim.value is None and claim.mail_event_id is not None
    if not cancelled and (
        after is None
        or before == after
        or (before is None and (previous.value is not None or previous.mail_event_id is None))
    ):
        return None
    if review:
        return "review"
    return "cancelled" if cancelled else "changed"


async def inbox_source(db: AsyncSession, claim: MemoryClaim) -> MemoryInboxSource | None:
    if claim.mail_event_id is not None:
        event = await memory_claim.mail_event(
            db,
            organization_id=claim.organization_id,
            event_id=claim.mail_event_id,
        )
        return _CONNECTOR_SOURCES.get(event.provider) if event is not None else None
    if claim.origin == "person" and claim.author_user_id is not None:
        return "reviewed"
    return None


async def queue_inbox_change(
    db: AsyncSession,
    *,
    claim: MemoryClaim,
    previous: MemoryClaim | None,
) -> None:
    """The same transaction writes the accepted ledger transition and queues its delivery."""
    if previous is None or claim.status not in ("current", "disputed"):
        return
    change = _change(claim, previous, review=claim.status == "disputed")
    now = datetime.now(UTC)
    # A closed historical amendment is visible on the timeline without paging anyone.
    if change is None or (claim.effective_to is not None and claim.effective_to <= now):
        return
    rule = await memory_claim.inbox_rule(db, organization_id=claim.organization_id)
    if rule is None or rule.mode == "off":
        return
    baseline = change != "review" or rule.include_review
    compare = rule.mode == "shadow" and rule.shadow_model
    if not baseline and not compare:
        return
    source = await inbox_source(db, claim)
    if source is None or source not in rule.sources:
        return
    revision_at = await memory_claim.latest_claim_revision(db, claim_id=claim.id)
    assert (
        revision_at is not None
    )  # Creation and conflict resolution persist a ledger revision first.
    key = f"memory-inbox:{claim.id}:{revision_at.isoformat()}:{POLICY_VERSION}:{rule.version}:{change}"
    payload = DeliverMemoryInbox(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        previous_id=previous.id,
        rule_version=rule.version,
        policy_version=POLICY_VERSION,
        change=change,
        revision_at=revision_at,
        source=source,
        source_event_id=claim.mail_event_id,
    )
    if baseline:
        await enqueue(
            db,
            DELIVER_MEMORY_INBOX,
            payload,
            organization_id=claim.organization_id,
            run_after=claim.effective_from,
            dedupe_key=key,
            dedupe_active=True,
        )
    if compare:
        await enqueue(
            db,
            SHADOW_MEMORY_INBOX,
            payload,
            organization_id=claim.organization_id,
            run_after=claim.effective_from,
            dedupe_key=f"{key}:model",
        )


async def current_inbox_scopes(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
) -> set[str]:
    member = await member_repo.get_active(db, organization_id=organization_id, user_id=user_id)
    if member is None or not AuthContext(
        user_id=user_id,
        organization_id=organization_id,
        role=member.role,
    ).has(Perm.CONTEXT_VIEW):
        return set()
    groups = await group_repo.list_memberships_in_org(
        db,
        organization_id=organization_id,
        user_id=user_id,
    )
    return {
        organization_owner_key(organization_id),
        *(group_owner_key(row.group_id) for row in groups),
    }


def inbox_evidence(
    rows: dict[UUID, MemoryClaim],
    *,
    claim_id: UUID,
    previous_id: UUID,
) -> tuple[MemoryClaim, MemoryClaim] | None:
    """Both sides of the comparison must still be granted and in the same audience."""
    claim, previous = rows.get(claim_id), rows.get(previous_id)
    if (
        claim is None
        or previous is None
        or not _shared(claim)
        or (claim.scope_key, claim.object_id, claim.agent_id)
        != (previous.scope_key, previous.object_id, previous.agent_id)
    ):
        return None
    return claim, previous


def authorized_inbox_source(
    claim: MemoryClaim,
    context: MemoryInboxContext,
    *,
    events: set[UUID],
) -> bool:
    if context.source == "reviewed":
        return claim.origin == "person" and claim.author_user_id is not None
    return context.source_event_id in events


async def inbox_wording(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    contexts: dict[UUID, MemoryInboxContext],
) -> dict[UUID, InboxWording]:
    scopes = await current_inbox_scopes(db, organization_id=organization_id, user_id=user_id)
    if not scopes:
        return {}
    claim_ids = {id_ for info in contexts.values() for id_ in (info.claim_id, info.previous_id)}
    rows = {
        row.id: row
        for row in await memory_claim.many(
            db,
            organization_id=organization_id,
            claim_ids=sorted(claim_ids),
        )
        if row.scope_key in scopes
    }
    objects = await memory_claim.inbox_objects(
        db,
        organization_id=organization_id,
        scopes=scopes,
        object_ids={row.object_id for row in rows.values() if row.object_id is not None},
    )
    authorized = await memory_claim.readable_event_ids(
        db,
        organization_id=organization_id,
        event_ids={
            info.source_event_id for info in contexts.values() if info.source_event_id is not None
        },
    )
    result: dict[UUID, InboxWording] = {}
    for id_, info in contexts.items():
        evidence = inbox_evidence(rows, claim_id=info.claim_id, previous_id=info.previous_id)
        if (
            evidence is None
            or not authorized_inbox_source(evidence[0], info, events=authorized)
            or (object_id := evidence[0].object_id) is None
            or (entity := objects.get(object_id)) is None
        ):
            continue
        claim, previous = evidence
        result[id_] = InboxWording(
            summary=f"{entity.name}: {_CHANGE_LABELS[info.change]}",
            params={
                "wording": "memory_deadline_change",
                "change": info.change,
                "object_name": entity.name,
                "before": _deadline(previous.value) or "",
                "after": _deadline(claim.value) or "",
                "source": info.source,
            },
        )
    return result


def pending_change(
    payload: DeliverMemoryInbox,
    claim: MemoryClaim,
    previous: MemoryClaim,
    *,
    now: datetime,
) -> bool:
    expected_status = "disputed" if payload.change == "review" else "current"
    return (
        claim.status == expected_status
        and (claim.effective_from is None or claim.effective_from <= now)
        and (claim.effective_to is None or now < claim.effective_to)
        and _change(claim, previous, review=payload.change == "review") == payload.change
    )
