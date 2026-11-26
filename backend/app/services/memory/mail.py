"""Review and apply Gmail deadline changes using the platform's portal and job queue.

Only an authenticated, exact sender and subject are admitted. The allowlisted
field is an explicit deadline line. No mailbox payload, credentials or arbitrary
instructions are passed to a model or put into a job.
"""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from email.utils import parseaddr
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.memory_keys import organization_owner_key
from app.core.permissions import AuthContext, Perm, Scope
from app.db.models.mcp_connection import McpConnection
from app.db.models.memory_claim import MemoryMailSource
from app.db.models.suggestion import SuggestionKind
from app.repositories import mcp_connection_repo, memory_claim, suggestion_repo
from app.schemas.memory import MemoryMailConfig, MemoryMailSourceRead, MemoryObjectRef
from app.services.access import member_context
from app.services.background_jobs import enqueue
from app.services.memory import _claims, sources
from app.services.portals.base import PolledEvent
from app.worker.jobs import APPLY_MEMORY_MAIL, ApplyMemoryMail

MAX_DAILY_EVENTS = 500
PORTAL = "google"
_DEADLINE_LINE = re.compile(r"^Deadline:[ \t]{1,12}(\d{4}-\d{2}-\d{2}|cancelled)[ \t]{0,12}$", re.M)


@dataclass(frozen=True)
class DeadlineEvent:
    received_at: datetime
    deadline: datetime | None
    quote: str


@dataclass(frozen=True)
class MailAdmission:
    queued: int
    complete: bool = True


def _date_at_midnight(text: str) -> datetime:
    return datetime.combine(date.fromisoformat(text), time.min, tzinfo=UTC)


def _parse(event: PolledEvent, source: MemoryMailSource) -> DeadlineEvent | None:
    payload = event.payload
    sender = payload.get("from")
    received = payload.get("received_at")
    body = payload.get("text")
    if (
        not event.delivery_id
        or len(event.delivery_id) > 200
        or payload.get("authenticated") is not True
        or not isinstance(sender, str)
        or parseaddr(sender)[1].casefold() != source.sender
        or payload.get("subject") != source.subject
        or not isinstance(received, str)
        or not isinstance(body, str)
    ):
        return None
    matches = list(_DEADLINE_LINE.finditer(body.replace("\r\n", "\n")))
    if len(matches) != 1:
        return None
    try:
        observed = datetime.fromisoformat(received)
        value = matches[0].group(1)
        deadline = None if value == "cancelled" else _date_at_midnight(value)
    except ValueError:
        return None
    if (
        observed.tzinfo is None
        or observed < source.admitted_from
        or observed > datetime.now(UTC) + timedelta(minutes=5)
    ):
        return None
    return DeadlineEvent(observed, deadline, matches[0].group(0))


def _authorized(source: MemoryMailSource, grant: McpConnection) -> bool:
    return (
        grant.id == source.grant_id
        and grant.organization_id == source.organization_id
        and grant.purpose == "portal"
        and grant.portal_key == PORTAL
        and grant.is_enabled
        and grant.oauth_payload is not None
        and not grant.authorization_expired
        and source.authorization_generation == grant.authorization_generation
    )


class MemoryMailService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _require_operator(ctx: AuthContext) -> None:
        if (
            ctx.key_scopes is not None
            or ctx.subject_is_publisher_fallback
            or not ctx.has(Perm.CONNECTIONS_MANAGE)
            or ctx.scope_for(Perm.CONTEXT_EDIT) != Scope.ALL
        ):
            raise AuthorizationError(
                message="Managing a memory source requires a member session with connections:manage and context:edit"
            )

    async def configuration(self, ctx: AuthContext) -> MemoryMailSourceRead | None:
        self._require_operator(ctx)
        source = await memory_claim.mail_source(self.db, ctx.organization_id)
        if source is None:
            return None
        grant = await mcp_connection_repo.get_portal_grant(
            self.db,
            organization_id=ctx.organization_id,
            portal_key=PORTAL,
        )
        return self._read(source, grant)

    @staticmethod
    def _read(source: MemoryMailSource, grant: McpConnection | None) -> MemoryMailSourceRead:
        return MemoryMailSourceRead(
            sender=source.sender,
            subject=source.subject,
            commitment=source.commitment,
            object_key=source.object_key,
            mode=source.mode,
            notify=source.notify,
            last_outcome=source.last_outcome,
            authorized=grant is not None and _authorized(source, grant),
        )

    async def configure(self, ctx: AuthContext, data: MemoryMailConfig) -> MemoryMailSourceRead:
        self._require_operator(ctx)
        found = await mcp_connection_repo.get_portal_grant(
            self.db,
            organization_id=ctx.organization_id,
            portal_key=PORTAL,
        )
        grant = (
            None
            if found is None
            else await mcp_connection_repo.get_by_id_for_update(self.db, found.id)
        )
        if (
            grant is None
            or not grant.is_enabled
            or grant.oauth_payload is None
            or grant.authorization_expired
        ):
            raise BadRequestError(
                message="Connect the organization's Gmail portal before enabling memory maintenance"
            )
        source = await memory_claim.mail_source(self.db, ctx.organization_id, lock=True)
        if source is not None and not _authorized(source, grant):
            await self._remove(source)
            source = None
        if source is None:
            source = MemoryMailSource(
                organization_id=ctx.organization_id,
                grant_id=grant.id,
                authorization_generation=grant.authorization_generation,
            )
        source.reviewer_id = ctx.subject_id
        source.generation = uuid4()
        source.sender = data.sender.casefold()
        source.subject = data.subject
        source.commitment = data.commitment
        source.object_key = data.object_key
        source.mode = data.mode
        source.notify = data.notify
        source.admitted_from = datetime.now(UTC)
        source.last_outcome = None
        self.db.add(source)
        await self.db.flush()
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="memory.mail.configured",
            target_type="memory_source",
            target_id=str(grant.id),
            details={"mode": source.mode, "notify": source.notify},
        )
        return self._read(source, grant)

    async def disable(self, ctx: AuthContext) -> None:
        self._require_operator(ctx)
        source = await memory_claim.mail_source(self.db, ctx.organization_id, lock=True)
        if source is not None:
            await self._remove(source)
            await record_audit(
                self.db,
                actor_user_id=ctx.subject_id,
                organization_id=ctx.organization_id,
                action="memory.mail.disabled",
                target_type="memory_source",
                target_id=str(ctx.organization_id),
                details={},
            )

    async def _remove(self, source: MemoryMailSource) -> None:
        await _claims._hold_scope(
            self.db,
            organization_id=source.organization_id,
            scope_key=organization_owner_key(source.organization_id),
        )
        await memory_claim.remove_mail_source(self.db, source)

    async def _current_reviewer(self, source: MemoryMailSource) -> AuthContext | None:
        if source.reviewer_id is None:
            return None
        reviewer = await member_context(
            self.db,
            organization_id=source.organization_id,
            user_id=source.reviewer_id,
        )
        if (
            reviewer is None
            or not reviewer.has(Perm.CONNECTIONS_MANAGE)
            or reviewer.scope_for(Perm.CONTEXT_EDIT) != Scope.ALL
        ):
            return None
        return reviewer

    async def subscribed(self, grant: McpConnection, source: str) -> bool:
        if source != "gmail" or grant.organization_id is None:
            return False
        config = await memory_claim.mail_source(self.db, grant.organization_id)
        return (
            config is not None
            and _authorized(config, grant)
            and await self._current_reviewer(config) is not None
        )

    async def admit(self, grant: McpConnection, events: Sequence[PolledEvent]) -> MailAdmission:
        if grant.organization_id is None or not events:
            return MailAdmission(0)
        source = await memory_claim.mail_source(self.db, grant.organization_id, lock=True)
        if (
            source is None
            or not _authorized(source, grant)
            or await self._current_reviewer(source) is None
        ):
            return MailAdmission(0)
        start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
        remaining = MAX_DAILY_EVENTS - await memory_claim.mail_events_since(
            self.db,
            organization_id=grant.organization_id,
            since=start,
        )
        queued = 0
        for event in events:
            parsed = _parse(event, source)
            if parsed is None:
                continue
            if queued >= remaining:
                if await memory_claim.mail_seen(
                    self.db,
                    organization_id=grant.organization_id,
                    grant_id=grant.id,
                    delivery_id=event.delivery_id,
                ):
                    continue
                source.last_outcome = "daily_limit"
                return MailAdmission(queued, complete=False)
            event_id = await memory_claim.admit_mail(
                self.db,
                source=source,
                grant_id=grant.id,
                delivery_id=event.delivery_id,
                received_at=parsed.received_at,
                deadline=parsed.deadline,
                quote=parsed.quote,
            )
            if event_id is None:
                continue
            await enqueue(
                self.db,
                APPLY_MEMORY_MAIL,
                ApplyMemoryMail(organization_id=grant.organization_id, event_id=event_id),
                organization_id=grant.organization_id,
                concurrency_key=f"memory-mail:{grant.organization_id}",
            )
            queued += 1
        return MailAdmission(queued)

    async def apply(self, payload: ApplyMemoryMail) -> None:
        event = await memory_claim.mail_event(
            self.db,
            organization_id=payload.organization_id,
            event_id=payload.event_id,
        )
        if event is None or event.state != "queued":
            return
        grant = await mcp_connection_repo.get_by_id_for_update(self.db, event.grant_id)
        source = await memory_claim.mail_source(self.db, payload.organization_id, lock=True)
        event = await memory_claim.mail_event(
            self.db,
            organization_id=payload.organization_id,
            event_id=payload.event_id,
        )
        if source is None or event is None or event.state != "queued":
            return
        reviewer = await self._current_reviewer(source)
        if (
            grant is None
            or not _authorized(source, grant)
            or source.generation != event.generation
            or reviewer is None
        ):
            event.state = "withheld"
            source.last_outcome = "withheld"
            return
        if source.mode == "shadow":
            event.state = "shadow"
            source.last_outcome = "shadow"
            return

        identity = hashlib.sha256(
            f"{grant.id}/{grant.authorization_generation}/{source.sender}/{source.subject}/{source.commitment}".encode()
        ).hexdigest()
        value = event.deadline.date().isoformat() if event.deadline is not None else None
        statement = (
            f"{source.commitment} deadline: {value}"
            if value is not None
            else f"{source.commitment} deadline cancelled"
        )
        result = await sources.apply_observation(
            self.db,
            organization_id=payload.organization_id,
            observation=sources.SourceObservation(
                source_key=f"gmail:{identity}",
                delivery_id=event.delivery_id,
                quote=event.quote,
                object=MemoryObjectRef(
                    kind="commitment", name=source.commitment, external_key=source.object_key
                ),
                subject="deadline",
                statement=statement,
                value=value,
                effective_at=event.received_at,
            ),
            mail_event=event,
        )
        stored = result.memory
        event.state = (
            "unchanged"
            if not stored.created
            else "disputed"
            if stored.disputed
            else "late"
            if result.late
            else "applied"
        )
        source.last_outcome = event.state
        if source.notify and result.previous is not None and stored.created and not stored.disputed:
            await suggestion_repo.propose(
                self.db,
                organization_id=payload.organization_id,
                user_id=reviewer.subject_id,
                kind=SuggestionKind.FINDING.value,
                title="Commitment deadline changed",
                detail=None,
                payload={
                    "memory_mail": True,
                    "memory_object_id": str(stored.claim.object_id),
                    "memory_mail_grant_id": str(grant.id),
                    "memory_mail_authorization": str(grant.authorization_generation),
                    "deadline_before": result.previous.statement,
                    "deadline_after": statement,
                },
                dedupe_key=hashlib.sha256(
                    f"memory-mail:{event.id}:deadline-v1".encode()
                ).hexdigest(),
            )
