"""What the notification-center schema guarantees, against a real database.

Phase 1 of #1598 (`docs/design/notification-center-plan.md`) is schema only -
nothing in this repository writes to any of these tables yet. What a unit test
cannot prove is exactly what this design leans on: that the dedup unique
constraint actually rejects a second row for the same
`(recipient_user_id, event_type, occurrence_id)`, that a `notifications` row's
cascade takes its deliveries with it while an `announcements` row survives one
being deleted, and that every vocabulary CHECK constraint rejects a value
outside it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.announcement import Announcement
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.notification_delivery import DeliveryStatus, NotificationDelivery
from app.db.models.notification_preference import NotificationChannelPreference
from app.db.models.organization import Organization
from app.db.models.rag_document import RAGDocument
from app.db.models.sync_log import SyncLog
from app.db.models.user import User

pytestmark = pytest.mark.anyio


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
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
    return org


def _notification(recipient: User, org: Organization | None = None, **overrides) -> Notification:
    fields = {
        "id": uuid.uuid4(),
        "organization_id": org.id if org else None,
        "recipient_user_id": recipient.id,
        "event_type": NotificationEventType.BUDGET_EXCEEDED.value,
        "occurrence_id": str(uuid.uuid4()),
        "summary": "An agent's budget was exceeded.",
        "in_app_visible": True,
    }
    fields.update(overrides)
    return Notification(**fields)


class TestTheDedupConstraintRejectsADuplicate:
    async def test_the_same_recipient_event_and_occurrence_is_refused(self, db):
        recipient = await _user(db)
        occurrence_id = str(uuid.uuid4())
        db.add(_notification(recipient, occurrence_id=occurrence_id))
        await db.flush()

        db.add(_notification(recipient, occurrence_id=occurrence_id))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_retried_ingestion_carries_a_distinct_occurrence_id(self, db):
        """The regression the design's own review caught: `retry_ingestion` reparses
        the same document id, so without a distinct occurrence id per attempt a
        second failure would collide with the first's dedup key and be silently
        dropped by this same constraint."""
        recipient = await _user(db)
        document_id = uuid.uuid4()
        first_attempt = _notification(
            recipient,
            event_type=NotificationEventType.INGESTION_FAILED.value,
            occurrence_id=f"{document_id}:1",
        )
        second_attempt = _notification(
            recipient,
            event_type=NotificationEventType.INGESTION_FAILED.value,
            occurrence_id=f"{document_id}:2",
        )
        db.add_all([first_attempt, second_attempt])
        await db.flush()  # both persist - the constraint sees two different keys

    async def test_a_different_recipient_for_the_same_occurrence_is_accepted(self, db):
        """The constraint is per recipient - a report or announcement fanning out to
        several people writes one row each, all sharing one occurrence id."""
        first_recipient = await _user(db)
        second_recipient = await _user(db)
        occurrence_id = str(uuid.uuid4())
        db.add(_notification(first_recipient, occurrence_id=occurrence_id))
        db.add(_notification(second_recipient, occurrence_id=occurrence_id))
        await db.flush()


class TestTheEventTypeVocabulary:
    async def test_an_event_type_outside_the_vocabulary_is_refused(self, db):
        recipient = await _user(db)
        db.add(_notification(recipient, event_type="made_up_event"))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_every_catalogued_event_type_is_accepted(self, db):
        """The CHECK's list and the enum drift apart exactly once - when a value is
        added to the code and not the constraint - so every value is written
        through it here, read off the enum rather than repeated as a literal."""
        recipient = await _user(db)
        for event_type in NotificationEventType:
            db.add(_notification(recipient, event_type=event_type.value))
        await db.flush()


class TestANullOrganizationRow:
    async def test_a_deployment_wide_notification_needs_no_organization(self, db):
        """`configuration_changed` and an app-admin-audience `security_event` have no
        tenant to scope to (Decision 2) - the column is nullable, not a leftover."""
        recipient = await _user(db)
        db.add(
            _notification(
                recipient,
                organization_id=None,
                event_type=NotificationEventType.CONFIGURATION_CHANGED.value,
            )
        )
        await db.flush()


class TestForeignKeyBehaviour:
    async def test_deleting_the_organization_cascades_its_notifications(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _user(db)
        notification = _notification(recipient, org=org)
        db.add(notification)
        await db.flush()
        notification_id = notification.id

        await db.delete(org)
        await db.flush()

        assert (
            await db.execute(select(Notification).where(Notification.id == notification_id))
        ).scalar_one_or_none() is None

    async def test_deleting_the_recipient_cascades_their_notification(self, db):
        recipient = await _user(db)
        notification = _notification(recipient)
        db.add(notification)
        await db.flush()
        notification_id = notification.id

        await db.delete(recipient)
        await db.flush()

        assert (
            await db.execute(select(Notification).where(Notification.id == notification_id))
        ).scalar_one_or_none() is None

    async def test_deleting_a_notification_cascades_its_deliveries(self, db):
        """Retention's hard delete (Decision 8) must not be blocked by a delivery row
        that still references it - the reason the FK is cascading, not restrictive."""
        recipient = await _user(db)
        notification = _notification(recipient)
        db.add(notification)
        await db.flush()
        delivery = NotificationDelivery(
            id=uuid.uuid4(), notification_id=notification.id, channel="email"
        )
        db.add(delivery)
        await db.flush()
        delivery_id = delivery.id

        await db.delete(notification)
        await db.flush()

        assert (
            await db.execute(
                select(NotificationDelivery).where(NotificationDelivery.id == delivery_id)
            )
        ).scalar_one_or_none() is None

    async def test_deleting_an_announcement_nulls_its_notifications_instead_of_deleting_them(
        self, db
    ):
        """Decision 8 excludes `announcements` from the retention sweep specifically so
        the send survives past its recipients' rows being purged - the FK direction
        this proves is what keeps a manual delete from taking a frozen, self-contained
        `summary` down with it too."""
        actor = await _user(db)
        announcement = Announcement(
            id=uuid.uuid4(),
            actor_user_id=actor.id,
            body="Scheduled maintenance tonight.",
            audience_spec={"organizations": "all", "role": None},
            audience_description="all organizations",
        )
        db.add(announcement)
        await db.flush()
        recipient = await _user(db)
        notification = _notification(
            recipient,
            event_type=NotificationEventType.ANNOUNCEMENT.value,
            announcement_id=announcement.id,
        )
        db.add(notification)
        await db.flush()
        notification_id = notification.id

        await db.delete(announcement)
        await db.flush()
        await db.refresh(notification)
        assert notification.id == notification_id
        assert notification.announcement_id is None

    async def test_deleting_the_uploader_nulls_the_documents_initiator_column(self, db):
        uploader = await _user(db)
        document = RAGDocument(
            id=uuid.uuid4(),
            collection_name="acme-kb",
            filename="report.pdf",
            filetype="pdf",
            initiated_by_user_id=uploader.id,
        )
        db.add(document)
        await db.flush()

        await db.delete(uploader)
        await db.flush()
        await db.refresh(document)
        assert document.initiated_by_user_id is None

    async def test_deleting_the_triggering_user_nulls_the_sync_logs_column(self, db):
        triggerer = await _user(db)
        log = SyncLog(
            id=uuid.uuid4(),
            source="gdrive",
            collection_name="acme-kb",
            triggered_by_user_id=triggerer.id,
        )
        db.add(log)
        await db.flush()

        await db.delete(triggerer)
        await db.flush()
        await db.refresh(log)
        assert log.triggered_by_user_id is None


class TestRAGDocumentDefaultsTheIngestionAttemptToOne:
    async def test_a_freshly_created_document_starts_at_attempt_one(self, db):
        document = RAGDocument(
            id=uuid.uuid4(), collection_name="acme-kb", filename="report.pdf", filetype="pdf"
        )
        db.add(document)
        await db.flush()
        await db.refresh(document)
        assert document.ingestion_attempt == 1


class TestNotificationDeliveryConstraints:
    async def test_a_channel_outside_the_vocabulary_is_refused(self, db):
        """Only `email` ships today - `in_app` never gets a delivery row, since the
        `Notification` row itself is the in-app delivery."""
        recipient = await _user(db)
        notification = _notification(recipient)
        db.add(notification)
        await db.flush()
        db.add(
            NotificationDelivery(id=uuid.uuid4(), notification_id=notification.id, channel="sms")
        )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_status_outside_the_vocabulary_is_refused(self, db):
        recipient = await _user(db)
        notification = _notification(recipient)
        db.add(notification)
        await db.flush()
        db.add(
            NotificationDelivery(
                id=uuid.uuid4(),
                notification_id=notification.id,
                channel="email",
                status="delivered",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_freshly_claimed_row_defaults_to_pending_with_no_attempts(self, db):
        recipient = await _user(db)
        notification = _notification(recipient)
        db.add(notification)
        await db.flush()
        delivery = NotificationDelivery(
            id=uuid.uuid4(), notification_id=notification.id, channel="email"
        )
        db.add(delivery)
        await db.flush()
        await db.refresh(delivery)
        assert delivery.status == DeliveryStatus.PENDING.value
        assert delivery.attempts == 0


class TestNotificationPreferenceConstraints:
    async def test_the_same_user_event_and_channel_twice_is_refused(self, db):
        """The guarantee the upsert path (Decision 4) leans on: two concurrent
        first-time writes for the same pair cannot both insert, so exactly one row
        can ever exist for it."""
        user = await _user(db)
        db.add(
            NotificationChannelPreference(
                id=uuid.uuid4(),
                user_id=user.id,
                event_type=NotificationEventType.SECURITY_EVENT.value,
                channel="email",
            )
        )
        await db.flush()

        db.add(
            NotificationChannelPreference(
                id=uuid.uuid4(),
                user_id=user.id,
                event_type=NotificationEventType.SECURITY_EVENT.value,
                channel="email",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_channel_outside_the_vocabulary_is_refused(self, db):
        user = await _user(db)
        db.add(
            NotificationChannelPreference(
                id=uuid.uuid4(),
                user_id=user.id,
                event_type=NotificationEventType.SECURITY_EVENT.value,
                channel="sms",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_an_unset_preference_defaults_to_enabled(self, db):
        user = await _user(db)
        preference = NotificationChannelPreference(
            id=uuid.uuid4(),
            user_id=user.id,
            event_type=NotificationEventType.SECURITY_EVENT.value,
            channel="email",
        )
        db.add(preference)
        await db.flush()
        await db.refresh(preference)
        assert preference.enabled is True

    async def test_deleting_the_user_cascades_their_preferences(self, db):
        user = await _user(db)
        preference = NotificationChannelPreference(
            id=uuid.uuid4(),
            user_id=user.id,
            event_type=NotificationEventType.SECURITY_EVENT.value,
            channel="email",
        )
        db.add(preference)
        await db.flush()
        preference_id = preference.id

        await db.delete(user)
        await db.flush()

        assert (
            await db.execute(
                select(NotificationChannelPreference).where(
                    NotificationChannelPreference.id == preference_id
                )
            )
        ).scalar_one_or_none() is None
