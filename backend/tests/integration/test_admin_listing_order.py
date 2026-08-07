"""What an admin listing puts at the top of page one, asked of a real Postgres.

Three of the columns these two listings sort on are nullable, and Postgres
orders NULL *first* on a descending sort. So the conversations page - whose
default is `updated_at desc` - opened on every thread that had never been
written to, `updated_at` being null until the first edit, above the thread
updated a second ago. Those threads are the emptiest ones in the deployment and
they held the top of page one permanently.

The wrong order is invisible from the page itself: the admin table has no
"Updated" column, so there is no header to compare the rows against and nothing
that looks broken. Only a query answers it, and only a real database answers
what `NULLS FIRST` does - which is why these are here rather than in the unit
suite.

`get_conversations` (the member-facing listing in the same repository) already
coalesced `updated_at` to `created_at` for this reason; the admin path was the
outlier. Found sweeping the search paths for #372.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models.conversation import Conversation
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation as conversation_repo
from app.repositories import user as user_repo

pytestmark = pytest.mark.anyio

# `func.now()` is transaction-stable in Postgres, so every row written in one
# test would otherwise carry an identical `created_at` and order arbitrarily.
NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


async def _user(db, *, full_name: str | None = None) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        full_name=full_name,
        hashed_password="x",
        is_active=True,
        created_at=NOW,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db) -> Organization:
    founder = await _user(db)
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _conversation(
    db,
    organization: Organization,
    *,
    title: str | None,
    created_ago: timedelta,
    updated_ago: timedelta | None,
    owner: User | None = None,
) -> Conversation:
    conversation = Conversation(
        id=uuid.uuid4(),
        organization_id=organization.id,
        user_id=owner.id if owner else None,
        title=title,
        created_at=NOW - created_ago,
        updated_at=None if updated_ago is None else NOW - updated_ago,
    )
    db.add(conversation)
    await db.flush()
    return conversation


class TestTheDefaultConversationsPage:
    async def test_a_thread_nobody_edited_does_not_outrank_one_edited_a_second_ago(
        self, db
    ) -> None:
        """`updated_at` is null until the first message, and NULL sorts first on
        a descending order - so the never-used threads led the page."""
        organization = await _org(db)
        await _conversation(
            db,
            organization,
            title="never used",
            created_ago=timedelta(days=30),
            updated_ago=None,
        )
        await _conversation(
            db,
            organization,
            title="live",
            created_ago=timedelta(days=60),
            updated_ago=timedelta(seconds=1),
        )

        rows, _ = await conversation_repo.admin_list_with_users(db)

        assert [conversation.title for conversation, _, _ in rows] == ["live", "never used"]

    async def test_an_unedited_thread_orders_on_when_it_was_created(self, db) -> None:
        """Coalescing to `created_at` rather than pushing the nulls to the end:
        a thread created this morning belongs near the top, not after every
        thread that was ever edited."""
        organization = await _org(db)
        await _conversation(
            db,
            organization,
            title="opened this morning",
            created_ago=timedelta(hours=1),
            updated_ago=None,
        )
        await _conversation(
            db,
            organization,
            title="edited last year",
            created_ago=timedelta(days=400),
            updated_ago=timedelta(days=300),
        )

        rows, _ = await conversation_repo.admin_list_with_users(db)

        assert [conversation.title for conversation, _, _ in rows] == [
            "opened this morning",
            "edited last year",
        ]


class TestSortingOnAColumnThatCanBeEmpty:
    async def test_a_conversation_with_no_owner_sorts_last(self, db) -> None:
        """A conversation that arrived through a channel has no `user_id`, so
        the outer-joined email is null. "Sort by owner, descending" used to open
        on a page of dashes."""
        organization = await _org(db)
        owner = await _user(db)
        await _conversation(
            db,
            organization,
            title="from a channel",
            created_ago=timedelta(days=1),
            updated_ago=timedelta(days=1),
        )
        await _conversation(
            db,
            organization,
            title="from the dashboard",
            created_ago=timedelta(days=2),
            updated_ago=timedelta(days=2),
            owner=owner,
        )

        rows, _ = await conversation_repo.admin_list_with_users(db, sort_by="owner")

        assert [conversation.title for conversation, _, _ in rows] == [
            "from the dashboard",
            "from a channel",
        ]

    async def test_an_untitled_conversation_sorts_last(self, db) -> None:
        """No title is not the largest title."""
        organization = await _org(db)
        await _conversation(
            db,
            organization,
            title=None,
            created_ago=timedelta(days=1),
            updated_ago=timedelta(days=1),
        )
        await _conversation(
            db,
            organization,
            title="quarterly numbers",
            created_ago=timedelta(days=2),
            updated_ago=timedelta(days=2),
        )

        rows, _ = await conversation_repo.admin_list_with_users(db, sort_by="title")

        assert [conversation.title for conversation, _, _ in rows] == ["quarterly numbers", None]

    async def test_a_user_who_never_gave_a_name_sorts_last(self, db) -> None:
        await _user(db, full_name=None)
        await _user(db, full_name="Rita Vrataski")

        rows, _ = await user_repo.admin_list_with_counts(db, sort_by="full_name")

        assert [user.full_name for user, _ in rows] == ["Rita Vrataski", None]
