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
    async def test_listing_non_admins_filters_on_is_app_admin(self, mock_session):
        """`--clear` selects the non-admins to delete by `is_app_admin`, not the
        dropped `role` column, and deletes each through the reconciling single
        delete rather than a bulk statement that 500s on the personal-org FK
        (#1124)."""
        rows = [MagicMock(), MagicMock(), MagicMock()]
        mock_session.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
        )

        found = await user_repo.list_non_admins(mock_session)

        assert found == rows
        statement = str(mock_session.execute.call_args.args[0])
        assert "is_app_admin" in statement


class TestMemberRepositoryLock:
    """The lock a caller takes before deciding something from the role it reads.

    `change_role` and `remove` both read a membership, refuse or allow on the role
    they find, and then write that same row. Under `READ COMMITTED` that is the
    read-check-write race: an Owner promoting the target in between leaves an Admin
    demoting or removing a peer Admin, which is the authority both methods exist to
    protect (#700). The parameter is what the two callers pass; this is what says it
    reaches the database as a lock.
    """

    @staticmethod
    async def _sql(*, for_update: bool) -> str:
        from uuid import uuid4

        from sqlalchemy.dialects import postgresql

        from app.repositories import member as member_repo

        session = MagicMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: None),
        )

        await member_repo.get(
            session, organization_id=uuid4(), user_id=uuid4(), for_update=for_update
        )

        statement = session.execute.call_args.args[0]
        return str(statement.compile(dialect=postgresql.dialect()))

    @pytest.mark.anyio
    async def test_it_locks_the_row_when_asked(self):
        assert "FOR UPDATE" in await self._sql(for_update=True)

    @pytest.mark.anyio
    async def test_it_takes_no_lock_by_default(self):
        """A reader pays nothing. Every listing and permission check calls this."""
        assert "FOR UPDATE" not in await self._sql(for_update=False)


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


class TestOrganizationSecretRepository:
    """Promoting a departing owner's private keys before their row is deleted."""

    @pytest.mark.anyio
    async def test_promote_owned_private_to_org_only_touches_the_owners_private_rows(self):
        """`ck_secret_private_needs_owner` is why this runs before the `SET NULL`:
        an org key is left alone, and only the private ones this owner holds are
        flipped to org visibility (#9)."""
        from uuid import uuid4

        from sqlalchemy.dialects import postgresql

        from app.repositories import organization_secret as organization_secret_repo

        session = MagicMock()
        session.execute = AsyncMock(return_value=MagicMock(rowcount=2))
        session.flush = AsyncMock()

        owner_id = uuid4()
        count = await organization_secret_repo.promote_owned_private_to_org(
            session, owner_user_id=owner_id
        )

        assert count == 2
        sql = str(session.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
        assert "UPDATE organization_secrets SET visibility" in sql
        assert "owner_user_id" in sql
        assert "visibility =" in sql  # the WHERE narrows to private rows only
