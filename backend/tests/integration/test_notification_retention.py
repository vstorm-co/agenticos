"""`notification_repo.delete_expired` - the sweep query itself, against a real
database (#1598, Decision 8).

`tests/test_notification_tasks.py` proves the flow computes its two cutoffs
from the retention constants; this proves the query those cutoffs feed
actually draws the boundary the design describes: a *read* row ages out at
the shorter window regardless of how recently it was read, an *unread* row
gets until the longer outer bound, and nothing here ever touches an
`announcements` row - only the per-recipient deliveries a broadcast fanned
out to.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models.announcement import Announcement
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.user import User
from app.repositories import notification_repo

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
READ_CUTOFF = NOW - timedelta(days=90)
OUTER_CUTOFF = NOW - timedelta(days=365)


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


def _notification(recipient: User, **overrides) -> Notification:
    fields = {
        "id": uuid.uuid4(),
        "organization_id": None,
        "recipient_user_id": recipient.id,
        "event_type": NotificationEventType.RUN_COMPLETED.value,
        "occurrence_id": str(uuid.uuid4()),
        "summary": "A run completed.",
        "in_app_visible": True,
        "created_at": NOW,
        "read_at": None,
    }
    fields.update(overrides)
    return Notification(**fields)


async def _sweep(db) -> int:
    return await notification_repo.delete_expired(
        db, read_cutoff=READ_CUTOFF, outer_cutoff=OUTER_CUTOFF
    )


class TestTheReadWindow:
    async def test_a_read_row_past_ninety_days_is_dropped(self, db):
        recipient = await _user(db)
        row = _notification(
            recipient, created_at=NOW - timedelta(days=91), read_at=NOW - timedelta(days=1)
        )
        db.add(row)
        await db.flush()

        removed = await _sweep(db)

        assert removed == 1
        assert await db.get(Notification, row.id) is None

    async def test_a_read_row_just_under_ninety_days_survives(self, db):
        recipient = await _user(db)
        row = _notification(
            recipient, created_at=NOW - timedelta(days=89), read_at=NOW - timedelta(days=1)
        )
        db.add(row)
        await db.flush()

        removed = await _sweep(db)

        assert removed == 0
        assert await db.get(Notification, row.id) is not None

    async def test_a_row_read_yesterday_but_created_past_the_window_still_drops(self, db):
        """The window is age since creation, not age since read - a row opened
        the day before its ninety-first day still ages out on schedule."""
        recipient = await _user(db)
        row = _notification(
            recipient, created_at=NOW - timedelta(days=95), read_at=NOW - timedelta(hours=1)
        )
        db.add(row)
        await db.flush()

        removed = await _sweep(db)

        assert removed == 1


class TestTheOuterBound:
    async def test_an_unread_row_past_ninety_days_but_under_a_year_survives(self, db):
        recipient = await _user(db)
        row = _notification(recipient, created_at=NOW - timedelta(days=120), read_at=None)
        db.add(row)
        await db.flush()

        removed = await _sweep(db)

        assert removed == 0
        assert await db.get(Notification, row.id) is not None

    async def test_an_unread_row_past_a_year_is_dropped(self, db):
        recipient = await _user(db)
        row = _notification(recipient, created_at=NOW - timedelta(days=366), read_at=None)
        db.add(row)
        await db.flush()

        removed = await _sweep(db)

        assert removed == 1
        assert await db.get(Notification, row.id) is None

    async def test_a_read_row_past_a_year_is_dropped_by_the_outer_bound_too(self, db):
        recipient = await _user(db)
        row = _notification(
            recipient, created_at=NOW - timedelta(days=366), read_at=NOW - timedelta(days=365)
        )
        db.add(row)
        await db.flush()

        removed = await _sweep(db)

        assert removed == 1


class TestAnnouncementsAreUntouched:
    async def test_the_announcement_row_survives_its_deliveries_being_swept(self, db):
        sender = await _user(db)
        recipient = await _user(db)
        announcement = Announcement(
            id=uuid.uuid4(),
            actor_user_id=sender.id,
            body="Maintenance tonight",
            audience_spec={"organizations": "all", "role": None},
            audience_description="All organizations",
        )
        db.add(announcement)
        await db.flush()
        db.add(
            _notification(
                recipient,
                event_type=NotificationEventType.ANNOUNCEMENT.value,
                announcement_id=announcement.id,
                occurrence_id=str(announcement.id),
                created_at=NOW - timedelta(days=366),
                read_at=None,
            )
        )
        await db.flush()

        removed = await _sweep(db)

        assert removed == 1
        assert await db.get(Announcement, announcement.id) is not None


class TestUnrelatedRowsAreLeftAlone:
    async def test_a_row_inside_both_windows_is_not_counted(self, db):
        recipient = await _user(db)
        db.add(_notification(recipient, created_at=NOW - timedelta(days=1), read_at=None))
        await db.flush()

        removed = await _sweep(db)

        assert removed == 0
        rows = (await db.execute(select(Notification))).scalars().all()
        assert len(rows) == 1
