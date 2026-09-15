"""The notification write path and the four gate-aware reads, against a real
database (#1598, phase 2 of `docs/design/notification-center-plan.md`).

Decisions 2-4's write-side guarantees (dedup, preference resolution, mandatory
bypass, the savepoint) and Decision 7's read-side gate - the one predicate the
inbox, the unread count, mark-one-read and mark-all-read all share - are both
built on real SQL (`ON CONFLICT`, a forced `IntegrityError`, `resolve_access`
against a real grant-less row) that a mocked repository cannot exercise.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.permissions import AuthContext
from app.db.models.announcement import Announcement
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.notification_delivery import NotificationDelivery
from app.db.models.notification_preference import NotificationChannelPreference
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services import notification_center
from app.services.notification_center import NotificationCenterService

pytestmark = pytest.mark.anyio


async def _user(db, *, is_app_admin: bool = False, **overrides) -> User:
    fields = {
        "id": uuid.uuid4(),
        "email": f"{uuid.uuid4().hex}@example.com",
        "hashed_password": "x",
        "is_active": True,
        "is_app_admin": is_app_admin,
    }
    fields.update(overrides)
    user = User(**fields)
    db.add(user)
    await db.flush()
    return user


async def _org(db, owner: User) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=owner.id, role="owner")
    )
    await db.flush()
    return org


async def _member(db, org: Organization, *, role: str) -> User:
    user = await _user(db)
    db.add(OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role=role))
    await db.flush()
    return user


def _ctx(user: User, org: Organization, *, role: str) -> AuthContext:
    return AuthContext(
        user_id=user.id, organization_id=org.id, role=role, is_app_admin=user.is_app_admin
    )


class TestWriteDedup:
    async def test_a_duplicate_occurrence_writes_nothing_the_second_time(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        service = NotificationCenterService(db)

        first = await service.write(
            recipients=[recipient.id],
            event_type=NotificationEventType.BUDGET_EXCEEDED,
            occurrence_id="run-1",
            summary="Budget exceeded",
            organization_id=org.id,
        )
        second = await service.write(
            recipients=[recipient.id],
            event_type=NotificationEventType.BUDGET_EXCEEDED,
            occurrence_id="run-1",
            summary="Budget exceeded",
            organization_id=org.id,
        )
        assert len(first) == 1
        assert second == []
        rows = (
            (
                await db.execute(
                    select(Notification).where(Notification.recipient_user_id == recipient.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    async def test_a_written_row_gets_an_email_delivery_by_default(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        service = NotificationCenterService(db)

        [notification] = await service.write(
            recipients=[recipient.id],
            event_type=NotificationEventType.RUN_COMPLETED,
            occurrence_id="run-2",
            summary="Run completed",
            organization_id=org.id,
        )
        deliveries = (
            (
                await db.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.notification_id == notification.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [d.channel for d in deliveries] == ["email"]


class TestPreferenceResolution:
    async def test_in_app_off_still_writes_the_row_but_hides_it_from_the_inbox(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        db.add(
            NotificationChannelPreference(
                id=uuid.uuid4(),
                user_id=recipient.id,
                event_type=NotificationEventType.RUN_FAILED.value,
                channel="in_app",
                enabled=False,
            )
        )
        await db.flush()
        service = NotificationCenterService(db)

        [notification] = await service.write(
            recipients=[recipient.id],
            event_type=NotificationEventType.RUN_FAILED,
            occurrence_id="run-3",
            summary="Run failed",
            organization_id=org.id,
        )
        assert notification.in_app_visible is False
        # Still the dedup anchor, and still gets its email delivery.
        deliveries = (
            (
                await db.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.notification_id == notification.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(deliveries) == 1

    async def test_email_off_writes_no_delivery_row(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        db.add(
            NotificationChannelPreference(
                id=uuid.uuid4(),
                user_id=recipient.id,
                event_type=NotificationEventType.RUN_FAILED.value,
                channel="email",
                enabled=False,
            )
        )
        await db.flush()
        service = NotificationCenterService(db)

        [notification] = await service.write(
            recipients=[recipient.id],
            event_type=NotificationEventType.RUN_FAILED,
            occurrence_id="run-4",
            summary="Run failed",
            organization_id=org.id,
        )
        assert notification.in_app_visible is True
        deliveries = (
            (
                await db.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.notification_id == notification.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert deliveries == []

    async def test_the_legacy_column_governs_email_for_a_lifecycle_event(self, db):
        """`budget_exceeded`'s email channel reads `notify_budget_alerts`, not the
        new preference table (Decision 4) - switching only the legacy column off
        is enough to suppress the delivery row, with no `notification_preferences`
        row involved at all."""
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        recipient.notify_budget_alerts = False
        await db.flush()
        service = NotificationCenterService(db)

        [notification] = await service.write(
            recipients=[recipient.id],
            event_type=NotificationEventType.BUDGET_EXCEEDED,
            occurrence_id="run-5",
            summary="Budget exceeded",
            organization_id=org.id,
        )
        deliveries = (
            (
                await db.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.notification_id == notification.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert deliveries == []


class TestMandatoryEvents:
    async def test_a_mandatory_event_ignores_preferences_on_both_channels(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        admin = await _member(db, org, role="admin")
        db.add(
            NotificationChannelPreference(
                id=uuid.uuid4(),
                user_id=admin.id,
                event_type=NotificationEventType.SECURITY_EVENT.value,
                channel="in_app",
                enabled=False,
            )
        )
        await db.flush()
        service = NotificationCenterService(db)

        [notification] = await service.write(
            recipients=[admin.id],
            event_type=NotificationEventType.SECURITY_EVENT,
            occurrence_id="audit-1",
            summary="A secret was rotated",
            organization_id=org.id,
        )
        assert notification.in_app_visible is True
        deliveries = (
            (
                await db.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.notification_id == notification.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(deliveries) == 1

    async def test_a_metered_mandatory_write_within_budget_still_writes(self, db, monkeypatch):
        owner = await _user(db)
        org = await _org(db, owner)
        admin = await _member(db, org, role="admin")
        service = NotificationCenterService(db)

        async def _allowed(**_kwargs):
            return notification_center.rate_limit.Decision(allowed=True, retry_after_seconds=0)

        monkeypatch.setattr(notification_center.rate_limit, "consume", _allowed)

        written = await service.write(
            recipients=[admin.id],
            event_type=NotificationEventType.SECURITY_EVENT,
            occurrence_id="audit-2b",
            summary="A secret was rotated",
            organization_id=org.id,
            actor_user_id=owner.id,
        )
        assert len(written) == 1

    async def test_a_rate_limited_mandatory_write_writes_nothing(self, db, monkeypatch):
        owner = await _user(db)
        org = await _org(db, owner)
        admin = await _member(db, org, role="admin")
        service = NotificationCenterService(db)

        async def _blocked(**_kwargs):
            return notification_center.rate_limit.Decision(allowed=False, retry_after_seconds=30)

        monkeypatch.setattr(notification_center.rate_limit, "consume", _blocked)

        written = await service.write(
            recipients=[admin.id],
            event_type=NotificationEventType.SECURITY_EVENT,
            occurrence_id="audit-2",
            summary="A secret was rotated",
            organization_id=org.id,
            actor_user_id=owner.id,
        )
        assert written == []
        rows = (
            (
                await db.execute(
                    select(Notification).where(Notification.recipient_user_id == admin.id)
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


class TestSavepointSafety:
    async def test_a_successful_write_under_a_savepoint_still_writes(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        service = NotificationCenterService(db)
        written = await service.write(
            recipients=[recipient.id],
            event_type=NotificationEventType.RUN_COMPLETED,
            occurrence_id="run-savepoint-ok",
            summary="Run completed",
            organization_id=org.id,
            use_savepoint=True,
        )
        assert len(written) == 1

    async def test_a_failed_write_under_a_savepoint_does_not_poison_the_session(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        service = NotificationCenterService(db)

        written = await service.write(
            recipients=[uuid.uuid4()],  # no such user - FK violation
            event_type=NotificationEventType.RUN_COMPLETED,
            occurrence_id="run-6",
            summary="Run completed",
            organization_id=org.id,
            use_savepoint=True,
        )
        assert written == []
        # The caller's own transaction is still usable - a real write goes through.
        db.add(await _user(db))
        await db.flush()

    async def test_a_failed_write_without_a_savepoint_propagates(self, db):
        service = NotificationCenterService(db)
        with pytest.raises(Exception):  # noqa: B017 - an IntegrityError from asyncpg, not ours to name
            await service.write(
                recipients=[uuid.uuid4()],
                event_type=NotificationEventType.RUN_COMPLETED,
                occurrence_id="run-7",
                summary="Run completed",
            )
        await db.rollback()


class TestReadGateNone:
    async def test_an_ungated_event_is_always_visible(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="viewer")
        service = NotificationCenterService(db)
        await service.write(
            recipients=[recipient.id],
            event_type=NotificationEventType.RUN_COMPLETED,
            occurrence_id="run-8",
            summary="Run completed",
            organization_id=org.id,
        )
        rows, strip = await service.list_inbox(
            _ctx(recipient, org, role="viewer"), after=None, limit=10
        )
        assert len(rows) == 1
        assert strip[rows[0].id] is False


class TestReadGateApprovalDegrade:
    async def test_a_decider_keeps_the_link_a_non_decider_loses_it(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        decider = await _member(db, org, role="operator")  # APPROVALS_DECIDE: ALL
        non_decider = await _member(db, org, role="member")  # no APPROVALS_DECIDE
        service = NotificationCenterService(db)
        await service.write(
            recipients=[decider.id, non_decider.id],
            event_type=NotificationEventType.APPROVAL_REQUESTED,
            occurrence_id="approval-1",
            summary="A tool call needs a decision",
            context_url="https://app.example.com/approvals/1",
            organization_id=org.id,
        )

        decider_rows, decider_strip = await service.list_inbox(
            _ctx(decider, org, role="operator"), after=None, limit=10
        )
        assert decider_strip[decider_rows[0].id] is False

        non_decider_rows, non_decider_strip = await service.list_inbox(
            _ctx(non_decider, org, role="member"), after=None, limit=10
        )
        assert non_decider_strip[non_decider_rows[0].id] is True


class TestReadGateOrgAdminOrAppAdmin:
    async def test_an_org_scoped_security_event_excludes_a_plain_member(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        admin = await _member(db, org, role="admin")
        member = await _member(db, org, role="member")
        service = NotificationCenterService(db)
        await service.write(
            recipients=[admin.id, member.id],
            event_type=NotificationEventType.SECURITY_EVENT,
            occurrence_id="audit-3",
            summary="A secret was rotated",
            organization_id=org.id,
        )

        admin_rows, _ = await service.list_inbox(
            _ctx(admin, org, role="admin"), after=None, limit=10
        )
        assert len(admin_rows) == 1
        member_rows, _ = await service.list_inbox(
            _ctx(member, org, role="member"), after=None, limit=10
        )
        assert member_rows == []

    async def test_a_deployment_wide_security_event_needs_is_app_admin(self, db):
        app_admin = await _user(db, is_app_admin=True)
        owner = await _user(db)
        org = await _org(db, owner)
        ordinary = await _member(db, org, role="admin")
        service = NotificationCenterService(db)
        await service.write(
            recipients=[app_admin.id, ordinary.id],
            event_type=NotificationEventType.SECURITY_EVENT,
            occurrence_id="audit-4",
            summary="Impersonation started",
            organization_id=None,
        )

        admin_ctx = AuthContext(
            user_id=app_admin.id, organization_id=org.id, role="member", is_app_admin=True
        )
        admin_rows, _ = await service.list_inbox(admin_ctx, after=None, limit=10)
        assert len(admin_rows) == 1

        ordinary_rows, _ = await service.list_inbox(
            _ctx(ordinary, org, role="admin"), after=None, limit=10
        )
        assert ordinary_rows == []


class TestReadGateAppAdmin:
    async def test_configuration_changed_needs_is_app_admin(self, db):
        app_admin = await _user(db, is_app_admin=True)
        owner = await _user(db)
        org = await _org(db, owner)
        ordinary = await _member(db, org, role="admin")
        service = NotificationCenterService(db)
        await service.write(
            recipients=[app_admin.id, ordinary.id],
            event_type=NotificationEventType.CONFIGURATION_CHANGED,
            occurrence_id="settings-1",
            summary="Deployment settings changed",
        )
        admin_ctx = AuthContext(
            user_id=app_admin.id, organization_id=org.id, role="member", is_app_admin=True
        )
        rows, _ = await service.list_inbox(admin_ctx, after=None, limit=10)
        assert len(rows) == 1
        ordinary_rows, _ = await service.list_inbox(
            _ctx(ordinary, org, role="admin"), after=None, limit=10
        )
        assert ordinary_rows == []


class TestReadGateRunsView:
    async def test_a_report_needs_current_runs_view(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        can_view = await _member(db, org, role="operator")
        cannot_view = await _member(db, org, role="viewer")
        service = NotificationCenterService(db)
        await service.write(
            recipients=[can_view.id, cannot_view.id],
            event_type=NotificationEventType.USAGE_REPORT,
            occurrence_id="report-1",
            summary="Weekly usage report",
            organization_id=org.id,
        )
        visible_rows, _ = await service.list_inbox(
            _ctx(can_view, org, role="operator"), after=None, limit=10
        )
        assert len(visible_rows) == 1
        hidden_rows, _ = await service.list_inbox(
            _ctx(cannot_view, org, role="viewer"), after=None, limit=10
        )
        assert hidden_rows == []


class TestReadGateCollectionsView:
    async def _kb(self, db, org: Organization, owner: User) -> KnowledgeBase:
        kb = KnowledgeBase(
            id=uuid.uuid4(),
            name="Docs",
            collection_name=f"kb-{uuid.uuid4().hex[:8]}",
            embedding_model="text-embedding-3-small",
            embedding_dim=1536,
            scope="org",
            visibility="private",
            owner_user_id=owner.id,
            organization_id=org.id,
        )
        db.add(kb)
        await db.flush()
        return kb

    async def test_an_owner_sees_it_a_member_without_a_grant_does_not(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        kb = await self._kb(db, org, owner)
        member = await _member(db, org, role="member")
        service = NotificationCenterService(db)
        await service.write(
            recipients=[owner.id, member.id],
            event_type=NotificationEventType.INGESTION_FAILED,
            occurrence_id="doc-1:1",
            summary="A document failed to ingest",
            render_context={"collection_id": str(kb.id)},
            organization_id=org.id,
        )
        owner_rows, _ = await service.list_inbox(
            _ctx(owner, org, role="owner"), after=None, limit=10
        )
        assert len(owner_rows) == 1
        member_rows, _ = await service.list_inbox(
            _ctx(member, org, role="member"), after=None, limit=10
        )
        assert member_rows == []

    async def test_a_row_with_no_collection_id_is_excluded(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        service = NotificationCenterService(db)
        await service.write(
            recipients=[owner.id],
            event_type=NotificationEventType.INGESTION_FAILED,
            occurrence_id="doc-2:1",
            summary="A document failed to ingest",
            organization_id=org.id,
        )
        rows, _ = await service.list_inbox(_ctx(owner, org, role="owner"), after=None, limit=10)
        assert rows == []

    async def test_a_row_naming_a_deleted_collection_is_excluded(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        service = NotificationCenterService(db)
        await service.write(
            recipients=[owner.id],
            event_type=NotificationEventType.INGESTION_FAILED,
            occurrence_id="doc-3:1",
            summary="A document failed to ingest",
            render_context={"collection_id": str(uuid.uuid4())},
            organization_id=org.id,
        )
        rows, _ = await service.list_inbox(_ctx(owner, org, role="owner"), after=None, limit=10)
        assert rows == []


class TestReadGateAnnouncementAudience:
    async def _announcement(self, db, *, actor: User, audience_spec: dict) -> Announcement:
        announcement = Announcement(
            id=uuid.uuid4(),
            actor_user_id=actor.id,
            body="Scheduled maintenance",
            audience_spec=audience_spec,
            audience_description="an audience",
        )
        db.add(announcement)
        await db.flush()
        return announcement

    async def test_all_organizations_reaches_any_current_member(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        member = await _member(db, org, role="member")
        announcement = await self._announcement(
            db, actor=owner, audience_spec={"organizations": "all", "role": None}
        )
        service = NotificationCenterService(db)
        await service.write(
            recipients=[member.id],
            event_type=NotificationEventType.ANNOUNCEMENT,
            occurrence_id=str(announcement.id),
            summary="Scheduled maintenance",
            announcement_id=announcement.id,
        )
        rows, _ = await service.list_inbox(_ctx(member, org, role="member"), after=None, limit=10)
        assert len(rows) == 1

    async def test_a_named_organization_excludes_someone_from_a_different_one(self, db):
        owner_a = await _user(db)
        org_a = await _org(db, owner_a)
        owner_b = await _user(db)
        org_b = await _org(db, owner_b)
        outsider = await _member(db, org_b, role="member")
        announcement = await self._announcement(
            db, actor=owner_a, audience_spec={"organizations": [str(org_a.id)], "role": None}
        )
        service = NotificationCenterService(db)
        await service.write(
            recipients=[outsider.id],
            event_type=NotificationEventType.ANNOUNCEMENT,
            occurrence_id=str(announcement.id),
            summary="Scheduled maintenance",
            announcement_id=announcement.id,
        )
        rows, _ = await service.list_inbox(
            _ctx(outsider, org_b, role="member"), after=None, limit=10
        )
        assert rows == []

    async def test_a_role_narrowed_announcement_excludes_a_plain_member(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        member = await _member(db, org, role="member")
        announcement = await self._announcement(
            db, actor=owner, audience_spec={"organizations": [str(org.id)], "role": "admin"}
        )
        service = NotificationCenterService(db)
        await service.write(
            recipients=[member.id],
            event_type=NotificationEventType.ANNOUNCEMENT,
            occurrence_id=str(announcement.id),
            summary="Scheduled maintenance",
            announcement_id=announcement.id,
        )
        rows, _ = await service.list_inbox(_ctx(member, org, role="member"), after=None, limit=10)
        assert rows == []

    async def test_a_row_with_no_announcement_id_is_excluded(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        service = NotificationCenterService(db)
        await service.write(
            recipients=[owner.id],
            event_type=NotificationEventType.ANNOUNCEMENT,
            occurrence_id="malformed-1",
            summary="Scheduled maintenance",
            organization_id=org.id,
        )
        rows, _ = await service.list_inbox(_ctx(owner, org, role="owner"), after=None, limit=10)
        assert rows == []

    async def test_a_row_naming_a_deleted_announcement_is_excluded(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        announcement = await self._announcement(
            db, actor=owner, audience_spec={"organizations": "all", "role": None}
        )
        service = NotificationCenterService(db)
        await service.write(
            recipients=[owner.id],
            event_type=NotificationEventType.ANNOUNCEMENT,
            occurrence_id=str(announcement.id),
            summary="Scheduled maintenance",
            announcement_id=announcement.id,
        )
        await db.delete(announcement)
        await db.flush()
        rows, _ = await service.list_inbox(_ctx(owner, org, role="owner"), after=None, limit=10)
        assert rows == []

    async def test_a_row_naming_an_announcement_that_never_existed_is_excluded(self, db):
        """`announcement_id` is `SET NULL` when the row it points at is deleted
        (Decision 8's own FK direction), so a live row referencing a truly
        missing announcement cannot arise through this service's own write
        path - exercised directly against a hand-built row instead."""
        owner = await _user(db)
        org = await _org(db, owner)
        service = NotificationCenterService(db)
        phantom = Notification(
            id=uuid.uuid4(),
            organization_id=None,
            recipient_user_id=owner.id,
            event_type=NotificationEventType.ANNOUNCEMENT.value,
            occurrence_id="phantom-1",
            summary="Scheduled maintenance",
            in_app_visible=True,
            announcement_id=uuid.uuid4(),
        )
        visible = await service._announcement_visible(_ctx(owner, org, role="owner"), phantom)
        assert visible is False

    async def test_an_announcement_naming_no_organizations_reaches_nobody(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        announcement = await self._announcement(
            db, actor=owner, audience_spec={"organizations": [], "role": None}
        )
        service = NotificationCenterService(db)
        await service.write(
            recipients=[owner.id],
            event_type=NotificationEventType.ANNOUNCEMENT,
            occurrence_id=str(announcement.id),
            summary="Scheduled maintenance",
            announcement_id=announcement.id,
        )
        rows, _ = await service.list_inbox(_ctx(owner, org, role="owner"), after=None, limit=10)
        assert rows == []


class TestListInboxPagination:
    async def test_a_second_page_starts_after_the_cursor(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        service = NotificationCenterService(db)
        for index in range(3):
            await service.write(
                recipients=[recipient.id],
                event_type=NotificationEventType.RUN_COMPLETED,
                occurrence_id=f"run-page-{index}",
                summary=f"Run {index} completed",
                organization_id=org.id,
            )
        ctx = _ctx(recipient, org, role="member")
        first_page, _ = await service.list_inbox(ctx, after=None, limit=2)
        assert len(first_page) == 2
        cursor = (first_page[-1].created_at, first_page[-1].id)
        second_page, _ = await service.list_inbox(ctx, after=cursor, limit=2)
        assert len(second_page) == 1
        assert second_page[0].id not in {row.id for row in first_page}

    async def test_a_fully_gated_backlog_exhausts_its_fetch_budget(self, db, monkeypatch):
        """Every candidate row is excluded, so the loop must run to its bound
        rather than looping forever - `_MAX_INBOX_FETCH_ROUNDS` lowered to 2 so
        the scenario needs only two rows, not hundreds."""
        monkeypatch.setattr(notification_center, "_MAX_INBOX_FETCH_ROUNDS", 2)
        owner = await _user(db)
        org = await _org(db, owner)
        member = await _member(db, org, role="member")
        service = NotificationCenterService(db)
        for index in range(2):
            await service.write(
                recipients=[member.id],
                event_type=NotificationEventType.SECURITY_EVENT,
                occurrence_id=f"audit-gated-{index}",
                summary="A secret was rotated",
                organization_id=org.id,
            )
        rows, _ = await service.list_inbox(_ctx(member, org, role="member"), after=None, limit=1)
        assert rows == []


class TestUnreadCountAndMarkRead:
    async def test_unread_count_only_counts_gate_visible_rows(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        admin = await _member(db, org, role="admin")
        member = await _member(db, org, role="member")
        service = NotificationCenterService(db)
        await service.write(
            recipients=[admin.id, member.id],
            event_type=NotificationEventType.SECURITY_EVENT,
            occurrence_id="audit-5",
            summary="A secret was rotated",
            organization_id=org.id,
        )
        assert await service.unread_count(_ctx(admin, org, role="admin")) == 1
        assert await service.unread_count(_ctx(member, org, role="member")) == 0

    async def test_marking_one_row_read_is_idempotent(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        service = NotificationCenterService(db)
        [notification] = await service.write(
            recipients=[recipient.id],
            event_type=NotificationEventType.RUN_COMPLETED,
            occurrence_id="run-9",
            summary="Run completed",
            organization_id=org.id,
        )
        ctx = _ctx(recipient, org, role="member")
        first, _ = await service.mark_one_read(ctx, notification.id)
        assert first.read_at is not None
        second, _ = await service.mark_one_read(ctx, notification.id)
        assert second.read_at == first.read_at

    async def test_marking_a_missing_row_is_refused(self, db):
        from app.core.exceptions import NotFoundError

        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        service = NotificationCenterService(db)
        with pytest.raises(NotFoundError):
            await service.mark_one_read(_ctx(recipient, org, role="member"), uuid.uuid4())

    async def test_marking_a_gate_excluded_row_reads_as_missing(self, db):
        from app.core.exceptions import NotFoundError

        owner = await _user(db)
        org = await _org(db, owner)
        member = await _member(db, org, role="member")
        service = NotificationCenterService(db)
        [notification] = await service.write(
            recipients=[member.id],
            event_type=NotificationEventType.SECURITY_EVENT,
            occurrence_id="audit-6",
            summary="A secret was rotated",
            organization_id=org.id,
        )
        with pytest.raises(NotFoundError):
            await service.mark_one_read(_ctx(member, org, role="member"), notification.id)

    async def test_mark_all_read_only_marks_gate_visible_rows(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        admin = await _member(db, org, role="admin")
        service = NotificationCenterService(db)
        await service.write(
            recipients=[admin.id],
            event_type=NotificationEventType.RUN_COMPLETED,
            occurrence_id="run-10",
            summary="Run completed",
            organization_id=org.id,
        )
        await service.write(
            recipients=[admin.id],
            event_type=NotificationEventType.SECURITY_EVENT,
            occurrence_id="audit-7",
            summary="A secret was rotated",
            organization_id=org.id,
        )
        marked = await service.mark_all_read(_ctx(admin, org, role="admin"))
        assert marked == 2  # admin holds both gates here

    async def test_mark_all_read_marks_nothing_when_every_candidate_is_gated_out(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        member = await _member(db, org, role="member")
        service = NotificationCenterService(db)
        await service.write(
            recipients=[member.id],
            event_type=NotificationEventType.SECURITY_EVENT,
            occurrence_id="audit-8",
            summary="A secret was rotated",
            organization_id=org.id,
        )
        marked = await service.mark_all_read(_ctx(member, org, role="member"))
        assert marked == 0


class TestRequireCaller:
    async def test_a_context_with_no_subject_is_refused(self, db):
        from app.core.exceptions import AuthorizationError

        owner = await _user(db)
        org = await _org(db, owner)
        anonymous = AuthContext(user_id=None, organization_id=org.id, role="member")
        service = NotificationCenterService(db)
        with pytest.raises(AuthorizationError):
            await service.unread_count(anonymous)


class TestCursorHelpers:
    def test_a_cursor_round_trips(self):
        created_at = datetime.now(UTC)
        notification_id = uuid.uuid4()
        raw = notification_center.encode_cursor(created_at, notification_id)
        decoded_created_at, decoded_id = notification_center.decode_cursor(raw)
        assert decoded_created_at == created_at
        assert decoded_id == notification_id

    def test_a_malformed_cursor_is_refused(self):
        from app.core.exceptions import BadRequestError

        with pytest.raises(BadRequestError):
            notification_center.decode_cursor("not-a-cursor")


class TestListInboxNoRows:
    async def test_an_empty_inbox_returns_nothing(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        service = NotificationCenterService(db)
        rows, strip = await service.list_inbox(
            _ctx(recipient, org, role="member"), after=None, limit=10
        )
        assert rows == []
        assert strip == {}
