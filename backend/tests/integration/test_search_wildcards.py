"""A search term is looked for, not interpreted - asked of a real Postgres.

Every listing with a search box built its `LIKE` operand by interpolating the
caller's string, so the wildcards in it were the caller's: `a_b` matched `axb`,
and a lone `%` matched every row and forced a scan no index could serve (#372).

A mock cannot answer this. The whole question is what Postgres does with the
pattern and its `ESCAPE` clause, so these run against the database and assert
the rows that come back - and the unpaged total beside them, because the count
is a second query that has to agree with the page.

The three searchable listings are here together on purpose: they now share one
helper, and a regression in it would otherwise be found by whichever of the
three happened to have a test.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.models.conversation import Conversation
from app.db.models.organization import Organization
from app.db.models.skill import Skill
from app.db.models.user import User
from app.repositories import conversation as conversation_repo
from app.repositories import skill as skill_repo
from app.repositories import user as user_repo

pytestmark = pytest.mark.anyio


async def _user(db, *, email: str, full_name: str | None = None) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        full_name=full_name,
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db) -> Organization:
    founder = await _user(db, email=f"{uuid.uuid4().hex}@example.com")
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _conversation(db, organization: Organization, *, title: str) -> Conversation:
    conversation = Conversation(
        id=uuid.uuid4(),
        organization_id=organization.id,
        title=title,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _skill(db, organization: Organization, *, name: str, description: str) -> Skill:
    skill = Skill(
        id=uuid.uuid4(),
        organization_id=organization.id,
        name=name,
        description=description,
        visibility="org",
    )
    db.add(skill)
    await db.flush()
    return skill


class TestSearchingUsers:
    async def test_an_underscore_is_a_character_and_not_a_wildcard(self, db) -> None:
        await _user(db, email="a_b@example.com")
        await _user(db, email="axb@example.com")

        rows, total = await user_repo.admin_list_with_counts(db, search="a_b")

        assert [user.email for user, _ in rows] == ["a_b@example.com"]
        assert total == 1

    async def test_a_percent_matches_the_row_holding_one_and_not_every_row(self, db) -> None:
        """The reason this is worth a test of its own: the failure is not an
        error, it is a full listing that looks like a working search."""
        await _user(db, email="discount@example.com", full_name="Ten % Off")
        await _user(db, email="somebody@example.com", full_name="Nobody Special")
        await _user(db, email="another@example.com", full_name="Also Nobody")

        rows, total = await user_repo.admin_list_with_counts(db, search="%")

        assert [user.full_name for user, _ in rows] == ["Ten % Off"]
        assert total == 1

    async def test_a_backslash_is_matched_literally(self, db) -> None:
        """Postgres' default `LIKE` escape is the backslash, so escaping with it
        made a searched-for backslash disappear into the escaping. The helper
        leaves the backslash alone and escapes with something else."""
        await _user(db, email="dom@example.com", full_name="DOMAIN\\user")
        await _user(db, email="plain@example.com", full_name="DOMAINuser")

        rows, total = await user_repo.admin_list_with_counts(db, search="DOMAIN\\user")

        assert [user.full_name for user, _ in rows] == ["DOMAIN\\user"]
        assert total == 1

    async def test_an_ordinary_term_still_matches_both_columns(self, db) -> None:
        """Escaping is not allowed to cost the search itself: the email and the
        name are two columns and a term reaches either."""
        await _user(db, email="rita@example.com", full_name="Someone Else")
        await _user(db, email="someone@example.com", full_name="Rita Vrataski")
        await _user(db, email="nobody@example.com", full_name="Nobody")

        rows, total = await user_repo.admin_list_with_counts(db, search="rita")

        assert sorted(user.email for user, _ in rows) == [
            "rita@example.com",
            "someone@example.com",
        ]
        assert total == 2


class TestSearchingConversations:
    async def test_an_underscore_is_a_character_and_not_a_wildcard(self, db) -> None:
        organization = await _org(db)
        await _conversation(db, organization, title="q1_report")
        await _conversation(db, organization, title="q1xreport")

        rows, total = await conversation_repo.admin_list_with_users(db, search="q1_report")

        assert [conversation.title for conversation, _, _ in rows] == ["q1_report"]
        assert total == 1

    async def test_a_percent_matches_the_row_holding_one_and_not_every_row(self, db) -> None:
        organization = await _org(db)
        await _conversation(db, organization, title="up 20% on last year")
        # Not merely a row without the term: one the trailing wildcard would
        # reach, so the test fails when the `%` stops being escaped.
        await _conversation(db, organization, title="20 people came")

        rows, total = await conversation_repo.admin_list_with_users(db, search="20%")

        assert [conversation.title for conversation, _, _ in rows] == ["up 20% on last year"]
        assert total == 1

    async def test_a_backslash_is_matched_literally(self, db) -> None:
        organization = await _org(db)
        await _conversation(db, organization, title="path C:\\temp")
        await _conversation(db, organization, title="path C:temp")

        rows, total = await conversation_repo.admin_list_with_users(db, search="C:\\temp")

        assert [conversation.title for conversation, _, _ in rows] == ["path C:\\temp"]
        assert total == 1


class TestSearchingSkills:
    async def test_an_underscore_is_a_character_and_not_a_wildcard(self, db) -> None:
        organization = await _org(db)
        owner = await _user(db, email=f"{uuid.uuid4().hex}@example.com")
        await _skill(db, organization, name="refund_policy", description="how to refund")
        await _skill(db, organization, name="refundxpolicy", description="unrelated")

        skills, total = await skill_repo.list_visible(
            db,
            organization_id=organization.id,
            user_id=owner.id,
            see_all=True,
            shared_ids=[],
            search="refund_policy",
        )

        assert [skill.name for skill in skills] == ["refund_policy"]
        assert total == 1

    async def test_a_percent_matches_the_row_holding_one_and_not_every_row(self, db) -> None:
        organization = await _org(db)
        owner = await _user(db, email=f"{uuid.uuid4().hex}@example.com")
        await _skill(db, organization, name="discounts", description="apply 10% off")
        # A row the unescaped trailing wildcard would reach through, so this
        # fails the moment the `%` is taken as a pattern again.
        await _skill(db, organization, name="onboarding", description="10 steps for a hire")

        skills, total = await skill_repo.list_visible(
            db,
            organization_id=organization.id,
            user_id=owner.id,
            see_all=True,
            shared_ids=[],
            search="10%",
        )

        assert [skill.name for skill in skills] == ["discounts"]
        assert total == 1

    async def test_a_backslash_is_matched_literally(self, db) -> None:
        organization = await _org(db)
        owner = await _user(db, email=f"{uuid.uuid4().hex}@example.com")
        await _skill(db, organization, name="windows-paths", description="use C:\\data")
        await _skill(db, organization, name="posix-paths", description="use C:data")

        skills, total = await skill_repo.list_visible(
            db,
            organization_id=organization.id,
            user_id=owner.id,
            see_all=True,
            shared_ids=[],
            search="C:\\data",
        )

        assert [skill.name for skill in skills] == ["windows-paths"]
        assert total == 1
