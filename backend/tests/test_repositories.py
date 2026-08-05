"""Tests for repository layer."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories import user as user_repo


class TestUserRepository:
    """Tests for user repository functions."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock async session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.mark.anyio
    async def test_get_by_email(self, mock_session):
        """Test get_by_email returns user."""
        mock_user = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_session.execute.return_value = mock_result

        result = await user_repo.get_by_email(mock_session, "test@example.com")

        assert result == mock_user

    @pytest.mark.anyio
    async def test_get_by_email_not_found(self, mock_session):
        """Test get_by_email returns None when not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await user_repo.get_by_email(mock_session, "notfound@example.com")

        assert result is None

    @pytest.mark.anyio
    async def test_creating_a_user_does_not_pass_a_role_column_that_no_longer_exists(
        self, mock_session
    ):
        """`users.role` was dropped in migration `0066`.

        The repository kept passing `role=` to the model, and SQLAlchemy's
        declarative constructor raises `TypeError` on an unmapped keyword - so
        *every* path that creates a user was broken: registration, Google OAuth,
        `agenticos user create`, and `agenticos cmd bootstrap`, which is the
        command the install instructions tell a new operator to run. Nothing
        failed until a real database was involved, so only the E2E job caught it.
        """
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock()

        user = await user_repo.create(
            mock_session,
            email="new@example.com",
            hashed_password="hashed",
        )

        assert user.email == "new@example.com"
        assert not hasattr(user, "role")

    @pytest.mark.anyio
    async def test_clearing_seeded_users_keeps_the_deployment_admins(self, mock_session):
        """`--clear` filters on `is_app_admin`, not on the dropped `role` column.

        Reading `User.role` raised before deleting anything, which made
        `agenticos cmd seed --clear` fail rather than clear.
        """
        mock_session.flush = AsyncMock()
        mock_session.execute.return_value = MagicMock(rowcount=3)

        removed = await user_repo.delete_non_admins(mock_session)

        assert removed == 3
        statement = str(mock_session.execute.call_args.args[0])
        assert "is_app_admin" in statement


class TestAgentRepositoryLock:
    """The lock `existing_ids_locked` takes when the approval writer resolves delegates."""

    @pytest.mark.anyio
    async def test_it_takes_for_key_share_not_for_no_key_update(self):
        """`FOR KEY SHARE` holds against deletion while letting ordinary updates through.

        `.with_for_update(key_share=True)` alone compiles to `FOR NO KEY UPDATE`
        in SQLAlchemy's PostgreSQL dialect, which needlessly blocks a concurrent
        agent update until the run transaction commits. `read=True, key_share=True`
        is what emits the intended `FOR KEY SHARE` - the lock an insert referencing
        the row takes anyway, so a concurrent delete still cannot slip in but an
        ordinary update is not held.
        """
        from uuid import uuid4

        from sqlalchemy.dialects import postgresql

        from app.repositories import agent as agent_repo

        session = MagicMock()
        session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=list)))

        await agent_repo.existing_ids_locked(session, {uuid4()}, organization_id=uuid4())

        statement = session.execute.call_args.args[0]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        assert "FOR KEY SHARE" in sql
        assert "FOR NO KEY UPDATE" not in sql
