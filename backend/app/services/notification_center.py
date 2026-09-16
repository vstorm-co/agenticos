"""The notification write path, and the four inbox reads (#1598).

`docs/design/notification-center-plan.md`, Decisions 2-4 and 7. `write()` turns
a resolved set of recipients into `notifications`/`notification_deliveries`
rows inside the caller's own transaction; the four read methods apply Decision
7's one gate-aware predicate to every row a listing, the unread count and
mark-all-read would otherwise return gate-blind.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.notification import Notification, NotificationChannel, NotificationEventType
from app.db.models.user import NotificationPreference
from app.repositories import knowledge_base as knowledge_base_repo
from app.repositories import member as member_repo
from app.repositories import notification as notification_repo
from app.services import rate_limit
from app.services.access import COLLECTION, resolve_access
from app.services.notification_catalog import ContentGate, content_gate_for, is_mandatory

logger = logging.getLogger(__name__)

# The email channel of these four event types is still governed by the three
# legacy boolean columns on `User` (Decision 4) - `usage_report` and
# `agent_usage_report` share one column, since both are the periodic digest the
# column was named for before this feature split it into two event types.
# Public: `notification_delivery.py`'s send-time recheck (Decision 3) reads the
# same authoritative lookup this write-time check does - two copies would be
# two things that could disagree about what "off" means for one event type.
LEGACY_EMAIL_COLUMN: dict[NotificationEventType, NotificationPreference] = {
    NotificationEventType.BUDGET_EXCEEDED: "notify_budget_alerts",
    NotificationEventType.APPROVAL_REQUESTED: "notify_approval_requests",
    NotificationEventType.USAGE_REPORT: "notify_usage_reports",
    NotificationEventType.AGENT_USAGE_REPORT: "notify_usage_reports",
}

_ESCALATION_ROLES = {OrgRoleName.OWNER.value, OrgRoleName.ADMIN.value}


def _build_togglable_pairs() -> frozenset[tuple[NotificationEventType, NotificationChannel]]:
    """Decision 4's preference surface: every `(event_type, channel)` pair
    this page may show a switch for - every non-mandatory event type's
    in-app channel, and every non-mandatory, non-legacy event type's email
    channel. Mandatory event types (`is_mandatory`) have no preference at
    all; the four `LEGACY_EMAIL_COLUMN` pairs stay `PATCH /users/me`'s."""
    pairs: set[tuple[NotificationEventType, NotificationChannel]] = set()
    for event_type in NotificationEventType:
        if is_mandatory(event_type):
            continue
        pairs.add((event_type, NotificationChannel.IN_APP))
        if event_type not in LEGACY_EMAIL_COLUMN:
            pairs.add((event_type, NotificationChannel.EMAIL))
    return frozenset(pairs)


# Built once at import time, not per request - the vocabulary is code-defined
# (Decision 1), not read from anywhere a request could change.
_TOGGLABLE_PAIRS = _build_togglable_pairs()


@dataclass(frozen=True)
class PreferenceItem:
    """One `(event_type, channel)` pair's current, defaulted-if-unset value."""

    event_type: NotificationEventType
    channel: NotificationChannel
    enabled: bool


# A mandatory event's write budget, keyed on (actor_user_id, event_type) -
# Decision 1's guard against an ordinary write access turning into an
# unmetered fan-out against every admin in an organization. The audit entry
# that names the write still records in full either way; only the
# notification is skipped over the limit.
_MANDATORY_WRITE_LIMIT = rate_limit.Limit(attempts=20, window_seconds=60)

# Bounds on the app-side work the gate-aware read paths do, since Decision 7's
# recheck cannot be pushed into a plain `COUNT`/`UPDATE` - each candidate row
# needs its own permission check. Generous enough that an ordinary inbox never
# notices either bound; a pathological backlog is truncated rather than
# unbounded.
_MAX_INBOX_FETCH_ROUNDS = 5
_UNREAD_CANDIDATE_CAP = 500


def encode_cursor(created_at: datetime, notification_id: uuid.UUID) -> str:
    """The opaque page token `GET /notifications` hands back as `next_cursor`.

    Carries both `created_at` and `id` (Decision 2): `created_at` alone cannot
    break a tie between rows one transaction wrote together for several
    recipients at once.
    """
    return f"{created_at.isoformat()}|{notification_id}"


def decode_cursor(raw: str) -> tuple[datetime, uuid.UUID]:
    try:
        created_at_raw, id_raw = raw.split("|", 1)
        created_at = datetime.fromisoformat(created_at_raw)
        notification_id = uuid.UUID(id_raw)
    except ValueError as exc:
        raise BadRequestError(message="Invalid pagination cursor", details={"cursor": raw}) from exc
    # `fromisoformat` accepts a timestamp with no offset and returns it naive
    # - `encode_cursor` never produces one, since `created_at` comes off a
    # `timestamptz` column, but a client is free to send one by hand.
    # Comparing that against `Notification.created_at` is what asyncpg
    # refuses, as a raw `DataError` rather than the 400 a malformed cursor
    # should be.
    if created_at.tzinfo is None:
        raise BadRequestError(message="Invalid pagination cursor", details={"cursor": raw})
    return created_at, notification_id


@dataclass(frozen=True)
class _Gate:
    """One row's outcome under Decision 7's recheck.

    `visible=False` is the exclude shape every gated event but one uses. The
    one exception, `approval_requested`, is always visible and instead reports
    whether its `context_url` (the decide link) should be withheld from a
    reader who no longer holds `approvals:decide` - the row is never rewritten,
    only what is served from it changes (Decision 7).
    """

    visible: bool
    strip_context_url: bool = False


class NotificationCenterService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -- write path -----------------------------------------------------

    async def write(
        self,
        *,
        recipients: list[uuid.UUID],
        event_type: NotificationEventType,
        occurrence_id: str,
        summary: str,
        context_url: str | None = None,
        render_context: dict[str, Any] | None = None,
        organization_id: uuid.UUID | None = None,
        announcement_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
        use_savepoint: bool = False,
    ) -> list[Notification]:
        """Resolve each recipient's channel preferences and write their rows.

        `use_savepoint=True` is for a caller whose own transaction cannot
        afford to be poisoned by a failure here - `AgentRunnerService.finish`
        is exactly such a context (Decision 2). A failure inside the savepoint
        rolls back to it and is logged as `notification_write_failed`; the
        caller's transaction proceeds and commits normally. Without it, a
        failure propagates to the caller, which is correct for a context built
        around this write succeeding.
        """
        mandatory = is_mandatory(event_type)
        if mandatory and actor_user_id is not None:
            decision = await rate_limit.consume(
                surface="notification_mandatory_write",
                caller=f"user:{actor_user_id}:{event_type.value}",
                limit=_MANDATORY_WRITE_LIMIT,
            )
            if not decision.allowed:
                logger.warning(
                    "notification_write_rate_limited",
                    extra={"event_type": event_type.value, "actor_user_id": str(actor_user_id)},
                )
                return []

        kwargs: dict[str, Any] = {
            "recipients": recipients,
            "event_type": event_type,
            "occurrence_id": occurrence_id,
            "summary": summary,
            "context_url": context_url,
            "render_context": render_context,
            "organization_id": organization_id,
            "announcement_id": announcement_id,
            "mandatory": mandatory,
        }
        if not use_savepoint:
            return await self._write_rows(**kwargs)
        try:
            async with self.db.begin_nested():
                return await self._write_rows(**kwargs)
        except Exception:  # pragma: no cover
            # Directly verified (a forced FK violation logs exactly this and
            # returns `[]`, checked with a spy on `logger.exception`) - not a
            # gap in the test, a gap in the tool. `coverage.py`'s tracer loses
            # this frame across the greenlet boundary SQLAlchemy's asyncpg
            # bridge switches through to unwind an exception raised inside
            # `begin_nested()`, the same class of trace loss `_write_rows`'s
            # own successful path does not hit, since nothing there crosses a
            # greenlet switch while unwinding.
            logger.exception(
                "notification_write_failed",
                extra={"event_type": event_type.value, "occurrence_id": occurrence_id},
            )
            return []

    async def _write_rows(
        self,
        *,
        recipients: list[uuid.UUID],
        event_type: NotificationEventType,
        occurrence_id: str,
        summary: str,
        context_url: str | None,
        render_context: dict[str, Any] | None,
        organization_id: uuid.UUID | None,
        announcement_id: uuid.UUID | None,
        mandatory: bool,
    ) -> list[Notification]:
        written: list[Notification] = []
        for recipient_id in recipients:
            in_app_visible = mandatory or await self._channel_enabled(
                recipient_id, event_type, NotificationChannel.IN_APP
            )
            notification = Notification(
                id=uuid.uuid4(),
                organization_id=organization_id,
                recipient_user_id=recipient_id,
                event_type=event_type.value,
                occurrence_id=occurrence_id,
                summary=summary,
                context_url=context_url,
                render_context=render_context,
                in_app_visible=in_app_visible,
                announcement_id=announcement_id,
            )
            inserted = await notification_repo.insert_notification_if_new(self.db, notification)
            if not inserted:
                continue
            written.append(notification)

            email_enabled = mandatory or await self.email_channel_enabled(recipient_id, event_type)
            if email_enabled:
                await notification_repo.insert_delivery(
                    self.db,
                    notification_id=notification.id,
                    channel=NotificationChannel.EMAIL.value,
                )
        return written

    async def _channel_enabled(
        self, user_id: uuid.UUID, event_type: NotificationEventType, channel: NotificationChannel
    ) -> bool:
        stored = await notification_repo.get_channel_preference(
            self.db, user_id=user_id, event_type=event_type.value, channel=channel.value
        )
        return True if stored is None else stored

    async def email_channel_enabled(
        self, user_id: uuid.UUID, event_type: NotificationEventType
    ) -> bool:
        """Exactly one authoritative lookup per event type (Decision 4): the
        legacy column for the four events it already governs, the preference
        table for every other event type - the two vocabularies never overlap.

        Public: also the send-time recheck `notification_delivery.py` performs
        immediately before calling the email provider (Decision 3), so a
        preference switched off during a provider outage is honoured by the
        retry that finally succeeds rather than by the write alone.
        """
        legacy_column = LEGACY_EMAIL_COLUMN.get(event_type)
        if legacy_column is not None:
            stored = await notification_repo.get_legacy_email_preference(
                self.db, user_id=user_id, column=legacy_column
            )
            return True if stored is None else stored
        return await self._channel_enabled(user_id, event_type, NotificationChannel.EMAIL)

    # -- reads, all gate-aware (Decision 7) ------------------------------

    async def list_inbox(
        self, ctx: AuthContext, *, after: tuple[datetime, uuid.UUID] | None, limit: int
    ) -> tuple[list[Notification], dict[uuid.UUID, bool]]:
        """A page of the inbox. Returns the visible rows together with which of
        them should have their `context_url` withheld when serialized - see
        `_Gate`."""
        user_id = self._require_caller(ctx)
        visible: list[Notification] = []
        strip: dict[uuid.UUID, bool] = {}
        cursor = after
        for _ in range(_MAX_INBOX_FETCH_ROUNDS):
            batch = await notification_repo.list_inbox_page(
                self.db,
                recipient_id=user_id,
                organization_id=ctx.organization_id,
                after=cursor,
                limit=limit,
            )
            if not batch:
                break
            for row in batch:
                gate = await self._gate(ctx, row)
                if gate.visible:
                    visible.append(row)
                    strip[row.id] = gate.strip_context_url
                    if len(visible) == limit:
                        return visible, strip
            cursor = (batch[-1].created_at, batch[-1].id)
            if len(batch) < limit:
                break
        return visible, strip

    async def unread_count(self, ctx: AuthContext) -> int:
        user_id = self._require_caller(ctx)
        candidates = await notification_repo.list_unread(
            self.db,
            recipient_id=user_id,
            organization_id=ctx.organization_id,
            cap=_UNREAD_CANDIDATE_CAP,
        )
        count = 0
        for row in candidates:
            gate = await self._gate(ctx, row)
            if gate.visible:
                count += 1
        return count

    async def mark_one_read(
        self, ctx: AuthContext, notification_id: uuid.UUID
    ) -> tuple[Notification, bool]:
        """Returns the row and whether its `context_url` should be withheld -
        see `_Gate`, the same pair `list_inbox` returns per row."""
        user_id = self._require_caller(ctx)
        notification = await notification_repo.get_own(
            self.db,
            notification_id=notification_id,
            recipient_id=user_id,
            organization_id=ctx.organization_id,
        )
        if notification is None:
            raise NotFoundError(
                message="Notification not found", details={"notification_id": str(notification_id)}
            )
        gate = await self._gate(ctx, notification)
        if not gate.visible:
            # The same rule a cross-tenant row already follows: a row the
            # reader may no longer see reads as absent, not as a 403.
            raise NotFoundError(
                message="Notification not found", details={"notification_id": str(notification_id)}
            )
        if notification.read_at is None:
            notification = await notification_repo.mark_read(
                self.db, notification, read_at=datetime.now(UTC)
            )
        return notification, gate.strip_context_url

    async def mark_all_read(self, ctx: AuthContext) -> int:
        user_id = self._require_caller(ctx)
        candidates = await notification_repo.list_unread(
            self.db,
            recipient_id=user_id,
            organization_id=ctx.organization_id,
            cap=_UNREAD_CANDIDATE_CAP,
        )
        visible_ids = []
        for row in candidates:
            gate = await self._gate(ctx, row)
            if gate.visible:
                visible_ids.append(row.id)
        return await notification_repo.mark_ids_read(
            self.db, ids=visible_ids, read_at=datetime.now(UTC)
        )

    # -- preferences (Decision 4) -----------------------------------------

    async def list_preferences(self, ctx: AuthContext) -> list[PreferenceItem]:
        """Every `(event_type, channel)` pair this page may show a switch for.

        Mandatory event types (`security_event`, `configuration_changed`) and
        the four legacy-column pairs (the email channel of `budget_exceeded`,
        `approval_requested`, `usage_report`, `agent_usage_report`) are never
        in this list - the first has no preference at all, the second is
        still `PATCH /users/me`'s (Decision 4). A pair with no stored row
        defaults enabled.
        """
        user_id = self._require_caller(ctx)
        stored = await notification_repo.list_channel_preferences(self.db, user_id=user_id)
        stored_map = {(row.event_type, row.channel): row.enabled for row in stored}
        # `NotificationEventType`'s own declared order, not the frozenset's -
        # a set iterates in an order nothing promises, and a page re-sorting
        # its own toggles between one load and the next is not a page anyone
        # can scan.
        return [
            PreferenceItem(
                event_type=event_type,
                channel=channel,
                enabled=stored_map.get((event_type.value, channel.value), True),
            )
            for event_type in NotificationEventType
            for channel in NotificationChannel
            if (event_type, channel) in _TOGGLABLE_PAIRS
        ]

    async def update_preference(
        self,
        ctx: AuthContext,
        *,
        event_type: NotificationEventType,
        channel: NotificationChannel,
        enabled: bool,
    ) -> PreferenceItem:
        """Upsert one pair - the whole of `PATCH`, per Decision 4.

        Raises:
            BadRequestError: `event_type` is mandatory or `(event_type,
                channel)` is one of the four legacy-column pairs - refused
                rather than silently writing a row nothing ever reads, which
                is what accepting it here would otherwise do.
        """
        user_id = self._require_caller(ctx)
        if (event_type, channel) not in _TOGGLABLE_PAIRS:
            raise BadRequestError(
                message="This event type is not preference-controlled here",
                details={"event_type": event_type.value, "channel": channel.value},
            )
        row = await notification_repo.upsert_channel_preference(
            self.db,
            user_id=user_id,
            event_type=event_type.value,
            channel=channel.value,
            enabled=enabled,
        )
        return PreferenceItem(event_type=event_type, channel=channel, enabled=row.enabled)

    @staticmethod
    def _require_caller(ctx: AuthContext) -> uuid.UUID:
        if ctx.user_id is None:
            raise AuthorizationError(message="Notifications require a signed-in caller")
        return ctx.user_id

    # -- the gate-aware predicate itself ---------------------------------

    async def _gate(self, ctx: AuthContext, notification: Notification) -> _Gate:
        gate = content_gate_for(NotificationEventType(notification.event_type))
        if gate is ContentGate.NONE:
            return _Gate(visible=True)
        if gate is ContentGate.DEGRADE:
            return _Gate(visible=True, strip_context_url=not ctx.has(Perm.APPROVALS_DECIDE))
        if gate is ContentGate.ORG_ADMIN_OR_APP_ADMIN:
            if notification.organization_id is None:
                return _Gate(visible=ctx.is_app_admin)
            return _Gate(visible=ctx.is_app_admin or ctx.role in _ESCALATION_ROLES)
        if gate is ContentGate.APP_ADMIN:
            return _Gate(visible=ctx.is_app_admin)
        if gate is ContentGate.RUNS_VIEW:
            return _Gate(visible=ctx.has(Perm.RUNS_VIEW))
        if gate is ContentGate.COLLECTIONS_VIEW:
            return _Gate(visible=await self._collections_visible(ctx, notification))
        if gate is ContentGate.ANNOUNCEMENT_AUDIENCE:
            return _Gate(visible=await self._announcement_visible(ctx, notification))
        raise AssertionError(f"unhandled content gate: {gate}")  # pragma: no cover

    async def _collections_visible(self, ctx: AuthContext, notification: Notification) -> bool:
        """`render_context["collection_id"]` is this event's own contract
        (Decision 1): the knowledge base an ingestion outcome is about, read
        back here rather than trusted from anywhere else."""
        render_context = notification.render_context or {}
        raw_collection_id = render_context.get("collection_id")
        if raw_collection_id is None:
            return False
        try:
            collection_id = uuid.UUID(str(raw_collection_id))
        except ValueError:
            # Nothing this service writes produces one, but `render_context`
            # is a JSONB blob with no schema enforcement - a malformed value
            # is treated the same as a collection that no longer exists,
            # rather than a 500 that takes the rest of the caller's inbox
            # down with this one row.
            return False
        kb = await knowledge_base_repo.get_by_id(self.db, collection_id)
        if kb is None:
            return False
        return await resolve_access(
            self.db, ctx, kb, Perm.COLLECTIONS_VIEW, resource_type=COLLECTION
        )

    async def _announcement_visible(self, ctx: AuthContext, notification: Notification) -> bool:
        # `ctx.user_id` is already guaranteed non-null here - every caller of
        # `_gate` goes through `_require_caller` first. `announcement_id` is
        # not: nothing ties it to `event_type` at the schema level, so a
        # malformed row is possible even though nothing this service writes
        # produces one.
        assert ctx.user_id is not None
        if notification.announcement_id is None:
            return False
        announcement = await notification_repo.get_announcement(
            self.db, notification.announcement_id
        )
        if announcement is None:
            return False
        spec = announcement.audience_spec or {}
        role = spec.get("role")
        organizations = spec.get("organizations")
        if organizations == "all":
            return await member_repo.has_any_membership(self.db, user_id=ctx.user_id, role=role)
        org_ids = [uuid.UUID(str(value)) for value in (organizations or [])]
        if not org_ids:
            return False
        return await member_repo.has_membership_in_any(
            self.db, user_id=ctx.user_id, organization_ids=org_ids, role=role
        )
