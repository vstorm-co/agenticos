"""The favourites band, against real rows.

The band is an `ORDER BY` and it has to be, because the sidebar is paged: a
favourite sorted into page two by recency would sit under fifty threads that are
not favourites, and grouping the page after it arrives cannot fix that (#929).
An ordering is the half a mocked session cannot answer at all.

Three more things only a database says: that starring twice is one row rather
than two, that a deleted conversation takes its stars with it, and that the star
is the *reader's* - two people looking at the same shared thread see two
different sidebars.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.conversation import Conversation
from app.db.models.conversation_favourite import ConversationFavourite
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation as conversation_repo

pytestmark = pytest.mark.anyio

_START = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


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
    owner: User,
    *,
    title: str,
    archived: bool = False,
    updated_at: datetime = _START,
) -> Conversation:
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=owner.id,
        organization_id=organization.id,
        title=title,
        is_archived=archived,
        created_at=_START,
        updated_at=updated_at,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _titles(db, organization: Organization, reader: User, **kwargs) -> list[str]:
    rows = await conversation_repo.get_conversations_by_user(
        db, reader.id, organization_id=organization.id, **kwargs
    )
    return [row.title or "" for row in rows]


class TestTheBandIsAnOrdering:
    async def test_a_favourite_rises_above_newer_threads(self, db) -> None:
        organization = await _org(db)
        reader = await _user(db)
        await _conversation(db, organization, reader, title="newest", updated_at=_START)
        await _conversation(
            db, organization, reader, title="middle", updated_at=_START - timedelta(days=1)
        )
        oldest = await _conversation(
            db, organization, reader, title="oldest", updated_at=_START - timedelta(days=2)
        )

        assert await _titles(db, organization, reader) == ["newest", "middle", "oldest"]

        await conversation_repo.set_favourite(
            db, user_id=reader.id, conversation_id=oldest.id, favourite=True
        )

        assert await _titles(db, organization, reader, favourites_first_for=reader.id) == [
            "oldest",
            "newest",
            "middle",
        ]

    async def test_the_chosen_sort_still_applies_inside_each_band(self, db) -> None:
        """Not "the order you starred them in", which is a second ordering
        nobody asked for."""
        organization = await _org(db)
        reader = await _user(db)
        first = await _conversation(db, organization, reader, title="alpha", updated_at=_START)
        second = await _conversation(
            db, organization, reader, title="zulu", updated_at=_START - timedelta(days=1)
        )
        await _conversation(
            db, organization, reader, title="mike", updated_at=_START - timedelta(days=2)
        )
        for conversation in (second, first):
            await conversation_repo.set_favourite(
                db, user_id=reader.id, conversation_id=conversation.id, favourite=True
            )

        ordered = await _titles(
            db,
            organization,
            reader,
            favourites_first_for=reader.id,
            sort_by="title",
            sort_dir="asc",
        )

        assert ordered == ["alpha", "zulu", "mike"]

    async def test_without_a_reader_the_order_is_untouched(self, db) -> None:
        """The admin listing asks for nobody's stars, and must not be reordered
        by whoever happens to have starred what."""
        organization = await _org(db)
        reader = await _user(db)
        await _conversation(db, organization, reader, title="newest", updated_at=_START)
        oldest = await _conversation(
            db, organization, reader, title="oldest", updated_at=_START - timedelta(days=2)
        )
        await conversation_repo.set_favourite(
            db, user_id=reader.id, conversation_id=oldest.id, favourite=True
        )

        assert await _titles(db, organization, reader) == ["newest", "oldest"]


class TestAStarIsOnePersonsOnly:
    async def test_two_readers_of_one_thread_see_two_sidebars(self, db) -> None:
        """The reason this is a join table. A boolean on the row would let the
        first person's star move the thread for the second."""
        organization = await _org(db)
        owner = await _user(db)
        other = await _user(db)
        thread = await _conversation(db, organization, owner, title="shared")
        await conversation_repo.set_favourite(
            db, user_id=owner.id, conversation_id=thread.id, favourite=True
        )

        assert await conversation_repo.favourite_ids(
            db, user_id=owner.id, conversation_ids=[thread.id]
        ) == {thread.id}
        assert (
            await conversation_repo.favourite_ids(
                db, user_id=other.id, conversation_ids=[thread.id]
            )
            == set()
        )

    async def test_starring_twice_is_one_row(self, db) -> None:
        organization = await _org(db)
        reader = await _user(db)
        thread = await _conversation(db, organization, reader, title="rota")

        for _ in range(2):
            await conversation_repo.set_favourite(
                db, user_id=reader.id, conversation_id=thread.id, favourite=True
            )

        assert await db.scalar(select(func.count(ConversationFavourite.user_id))) == 1

    async def test_unstarring_what_was_never_starred_is_not_an_error(self, db) -> None:
        organization = await _org(db)
        reader = await _user(db)
        thread = await _conversation(db, organization, reader, title="rota")

        await conversation_repo.set_favourite(
            db, user_id=reader.id, conversation_id=thread.id, favourite=False
        )

        assert await db.scalar(select(func.count(ConversationFavourite.user_id))) == 0

    async def test_a_deleted_conversation_takes_its_stars_with_it(self, db) -> None:
        organization = await _org(db)
        reader = await _user(db)
        thread = await _conversation(db, organization, reader, title="rota")
        await conversation_repo.set_favourite(
            db, user_id=reader.id, conversation_id=thread.id, favourite=True
        )

        await db.delete(thread)
        await db.flush()

        assert await db.scalar(select(func.count(ConversationFavourite.user_id))) == 0


class TestArchivingKeepsTheStarAndDropsTheBand:
    async def test_an_archived_favourite_is_still_starred(self, db) -> None:
        organization = await _org(db)
        reader = await _user(db)
        thread = await _conversation(db, organization, reader, title="rota", archived=True)
        await conversation_repo.set_favourite(
            db, user_id=reader.id, conversation_id=thread.id, favourite=True
        )

        assert await conversation_repo.favourite_ids(
            db, user_id=reader.id, conversation_ids=[thread.id]
        ) == {thread.id}


class TestTwoClicksAtOnceStillLeaveOneRow:
    async def test_a_held_star_does_not_make_the_second_one_fail(self, engine: AsyncEngine) -> None:
        """Deterministic on purpose, the shape #17's identity race uses: one
        request's insert is held open - uncommitted, holding the unique-index
        lock on the new row - while a second stars the same thread.

        `ON CONFLICT DO NOTHING` has the second block on that lock and, once the
        first commits, do nothing: one row, no error. The read-then-insert it
        replaces had both requests miss the `SELECT` and both `INSERT`, and the
        second violated the primary key - so a double click answered 500 and the
        sidebar rolled the star back off a thread that was in fact starred
        (#1254). Racing two calls through `gather` does not reproduce it: the
        pair serialises and the first commits before the second inserts.
        """
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as setup:
            organization = await _org(setup)
            reader = await _user(setup)
            thread = await _conversation(setup, organization, reader, title="rota")
            await setup.commit()

        session_a = factory()
        b_task: asyncio.Task[None] | None = None
        try:
            await conversation_repo.set_favourite(
                session_a, user_id=reader.id, conversation_id=thread.id, favourite=True
            )

            async def star_again() -> None:
                async with factory() as session_b:
                    await conversation_repo.set_favourite(
                        session_b, user_id=reader.id, conversation_id=thread.id, favourite=True
                    )
                    await session_b.commit()

            b_task = asyncio.create_task(star_again())
            await asyncio.sleep(0.4)
            assert not b_task.done()  # blocked on A's uncommitted insert

            await session_a.commit()

            await b_task
            b_task = None
        finally:
            if b_task is not None:
                b_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await b_task
            await session_a.close()

        async with factory() as session:
            assert await session.scalar(select(func.count(ConversationFavourite.user_id))) == 1
