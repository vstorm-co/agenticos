"""Tests for the MCP connection repository - the rows that hold third-party credentials.

A repository's behaviour *is* the statement it builds, so these tests read the
statement back rather than counting calls. Three of the predicates here are load
bearing in a way no "the repository was called" assertion would notice:

- ``get_org_scoped_by_id`` drops either of its two filters and a published agent
  starts running on another tenant's row, or on a member's personal token.
- ``get_by_id_for_update`` without ``FOR UPDATE`` lets two chat turns redeem the
  same OAuth refresh token, and with the model's eager join still attached
  Postgres refuses the lock outright.
- ``list_for_user`` is the order those locks are taken in; reorder it and two
  concurrent turns can deadlock on the same pair of rows.

That the lock is really acceptable to Postgres - the eager-join half - can only
be answered by a database, and is asserted in
``tests/integration/test_platform_flows.py``.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Executable

from app.db.models.mcp_connection import McpConnection
from app.repositories import mcp_connection_repo

pytestmark = pytest.mark.anyio


class _RecordingSession:
    """An ``AsyncSession`` stand-in that keeps the statements it was given."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.statements: list[Executable] = []
        self.added: list[McpConnection] = []
        self.deleted: list[McpConnection] = []
        self.flushes = 0
        self.refreshed: list[McpConnection] = []

    async def execute(self, statement: Executable) -> object:
        self.statements.append(statement)
        return self._results.pop(0)

    def add(self, instance: McpConnection) -> None:
        self.added.append(instance)

    async def delete(self, instance: McpConnection) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        self.flushes += 1

    async def refresh(self, instance: McpConnection) -> None:
        self.refreshed.append(instance)

    async def commit(self) -> None:
        raise AssertionError(
            "repositories must not commit - get_db_session owns the transaction boundary"
        )


class _Scalars(list[McpConnection]):
    """What ``.scalars()`` returns: iterable, and answers ``.all()``."""

    def all(self) -> list[McpConnection]:
        return list(self)


class _Result:
    """What ``AsyncSession.execute`` hands back, for the three shapes used here."""

    def __init__(self, *, scalar: object = None, rows: list[McpConnection] | None = None) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def scalar_one(self) -> object:
        return self._scalar

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


def _sql(session: _RecordingSession, index: int = -1) -> str:
    return str(session.statements[index].compile(dialect=postgresql.dialect()))


def _filters(session: _RecordingSession, index: int = -1) -> dict[str, Any]:
    """The values the recorded statement actually filters on."""
    return session.statements[index].compile(dialect=postgresql.dialect()).params


def _connection(**overrides: object) -> McpConnection:
    connection = McpConnection()
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "name": "github",
        "url": "https://example.com/mcp",
        "is_enabled": True,
        "last_status": None,
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        setattr(connection, key, value)
    return connection


class TestGetById:
    async def test_an_unknown_id_is_none_rather_than_an_error(self):
        """Every caller branches on ``None``; a raising lookup would turn a
        deleted connection into a 500 instead of a 404."""
        session = _RecordingSession(_Result(scalar=None))

        assert await mcp_connection_repo.get_by_id(session, uuid.uuid4()) is None

    async def test_the_row_is_looked_up_by_its_own_id(self):
        connection = _connection()
        session = _RecordingSession(_Result(scalar=connection))

        found = await mcp_connection_repo.get_by_id(session, connection.id)

        assert found is connection
        assert list(_filters(session).values()) == [connection.id]


class TestGetByIdForUpdate:
    """The read that guards an OAuth refresh. All three options matter."""

    @staticmethod
    async def _record() -> _RecordingSession:
        session = _RecordingSession(_Result(scalar=None))
        await mcp_connection_repo.get_by_id_for_update(session, uuid.uuid4())
        return session

    async def test_the_row_is_locked(self):
        """Without the lock, two turns reaching an expired token at the same
        moment both spend the refresh token - and a provider that rotates it
        invalidates whichever copy is redeemed second."""
        assert "FOR UPDATE" in _sql(await self._record())

    async def test_the_models_eager_join_is_dropped(self):
        """``McpConnection.user`` is a joined eager load, which makes this a
        LEFT OUTER JOIN - and Postgres refuses ``FOR UPDATE`` on the nullable
        side of one, so the lock would fail rather than merely be slow."""
        assert "JOIN" not in _sql(await self._record())

    async def test_the_columns_are_re_read_rather_than_taken_from_the_identity_map(self):
        """The whole point of waiting for the lock is to see what the other
        transaction committed. Without ``populate_existing`` the session hands
        back its cached copy - the stale token we were trying to replace."""
        session = await self._record()

        assert session.statements[-1].get_execution_options()["populate_existing"] is True


class TestGetOrgScopedById:
    async def test_the_lookup_names_the_organization_and_demands_an_org_connection(self):
        """Either filter missing is a different failure and both are severe: no
        organization means an agent spec can name a row in another tenant, and
        no scope means a shared agent can run on somebody's personal token."""
        session = _RecordingSession(_Result(scalar=None))
        connection_id, organization_id = uuid.uuid4(), uuid.uuid4()

        await mcp_connection_repo.get_org_scoped_by_id(
            session, connection_id=connection_id, organization_id=organization_id
        )

        assert set(_filters(session).values()) == {connection_id, organization_id, "org"}


class TestGetByName:
    async def test_a_name_is_only_unique_within_one_users_connections(self):
        """``uq_mcp_connections_user_name`` is per user, so a lookup that
        forgot the user would report somebody else's "github" as a collision
        and refuse a name this user is entitled to.

        The scope filter is the other half: an organization server called
        "github" is not a collision with a personal one, and treating it as one
        would refuse a name the member is entitled to for a row they cannot see.
        """
        session = _RecordingSession(_Result(scalar=None))
        user_id = uuid.uuid4()

        await mcp_connection_repo.get_by_name(session, user_id=user_id, name="github")

        assert set(_filters(session).values()) == {user_id, "github", "user"}


class TestListOauthConnections:
    """What the scheduled sweep is handed, and what it must never be handed."""

    async def test_a_flow_the_user_never_finished_is_left_out(self):
        """``oauth_start`` writes the row before the consent screen is shown, so
        a NULL ``oauth_payload`` is a connection nobody has authorized yet.
        Sweeping one would spend a query on a row with no token to renew and
        then write "Authorization expired" onto a plugin that never had one."""
        session = _RecordingSession(_Result(rows=[]))

        await mcp_connection_repo.list_oauth_connections(session)

        assert "mcp_connections.oauth_payload IS NOT NULL" in _sql(session)

    async def test_a_pasted_bearer_token_is_not_something_this_can_renew(self):
        """Only the OAuth rows have a refresh token to spend. A bearer
        connection swept alongside them would be marked as needing
        authorization the first time it was looked at."""
        session = _RecordingSession(_Result(rows=[]))

        await mcp_connection_repo.list_oauth_connections(session)

        assert _filters(session)["auth_type_1"] == "oauth"

    async def test_the_sweep_reads_the_whole_deployment_rather_than_one_tenant(self):
        """Deliberately unscoped, and the only query here that is. The sweep is
        about the deployment's health; a tenant filter would quietly reduce it
        to whichever organization was passed while still reporting success for
        every other one."""
        session = _RecordingSession(_Result(rows=[]))

        await mcp_connection_repo.list_oauth_connections(session)

        assert set(_filters(session).values()) == {"oauth"}

    async def test_the_matching_rows_come_back(self):
        rows = [_connection(auth_type="oauth"), _connection(auth_type="oauth")]
        session = _RecordingSession(_Result(rows=rows))

        assert await mcp_connection_repo.list_oauth_connections(session) == rows


class TestGetByOauthState:
    async def test_the_pending_flow_is_found_by_its_csrf_token(self):
        """The state token is the only thing authenticating the OAuth callback,
        so it is also the only thing that may select the row it completes."""
        pending = _connection(oauth_state="state-xyz")
        session = _RecordingSession(_Result(scalar=pending))

        found = await mcp_connection_repo.get_by_oauth_state(session, "state-xyz")

        assert found is pending
        assert list(_filters(session).values()) == ["state-xyz"]


class TestListForUser:
    async def test_connections_come_back_oldest_first(self):
        """This order is the lock order. ``_refresh_under_lock`` takes row locks
        as it walks this list, so two turns holding different subsets can only
        avoid deadlocking each other while every turn walks them the same way."""
        session = _RecordingSession(_Result(scalar=0), _Result(rows=[]))

        await mcp_connection_repo.list_for_user(session, user_id=uuid.uuid4())

        assert "ORDER BY mcp_connections.created_at ASC" in _sql(session)

    async def test_a_users_own_connections_are_the_only_ones_listed(self):
        session = _RecordingSession(_Result(scalar=0), _Result(rows=[]))
        user_id = uuid.uuid4()

        await mcp_connection_repo.list_for_user(session, user_id=user_id)

        assert _filters(session)["user_id_1"] == user_id

    async def test_an_organization_connection_is_never_in_a_persons_list(self):
        """Settings → Your connections is the one place a connection can be
        edited without holding ``connections:manage``. An organization row
        appearing there would be a shared credential anyone who could reach the
        page could repoint."""
        session = _RecordingSession(_Result(scalar=0), _Result(rows=[]))

        await mcp_connection_repo.list_for_user(session, user_id=uuid.uuid4())

        assert _filters(session)["scope_1"] == "user"

    async def test_by_default_a_disabled_connection_is_still_listed(self):
        """Settings has to show a connection the user switched off, or there is
        no way back to switching it on."""
        session = _RecordingSession(_Result(scalar=0), _Result(rows=[]))

        await mcp_connection_repo.list_for_user(session, user_id=uuid.uuid4())

        assert "mcp_connections.is_enabled IS true" not in _sql(session)

    async def test_enabled_only_is_what_a_chat_turn_asks_for(self):
        """A disabled connection reaching a turn would attach tools the user
        deliberately turned off."""
        session = _RecordingSession(_Result(scalar=0), _Result(rows=[]))

        await mcp_connection_repo.list_for_user(session, user_id=uuid.uuid4(), enabled_only=True)

        assert "mcp_connections.is_enabled IS true" in _sql(session)

    async def test_the_total_is_counted_over_the_same_filters_as_the_rows(self):
        """A total taken from an unfiltered query would tell the UI there are
        connections the listing never returns."""
        rows = [_connection(), _connection()]
        session = _RecordingSession(_Result(scalar=2), _Result(rows=rows))

        items, total = await mcp_connection_repo.list_for_user(
            session, user_id=uuid.uuid4(), enabled_only=True
        )

        assert items == rows
        assert total == 2
        assert "mcp_connections.is_enabled IS true" in _sql(session, index=0)


class TestListOrgScoped:
    async def test_only_this_organizations_shared_servers_are_listed(self):
        """Both filters carry weight. Without the organization the page shows
        another tenant's servers; without the scope it shows every member's
        personal token as if the organization owned it."""
        session = _RecordingSession(_Result(scalar=0), _Result(rows=[]))
        organization_id = uuid.uuid4()

        await mcp_connection_repo.list_org_scoped(session, organization_id=organization_id)

        assert set(_filters(session).values()) == {organization_id, "org"}

    async def test_connections_come_back_oldest_first(self):
        """Same order as ``list_for_user``, and for the same reason: a run that
        locks several rows walks them in list order, and two lists that disagree
        are two ways for concurrent turns to deadlock."""
        session = _RecordingSession(_Result(scalar=0), _Result(rows=[]))

        await mcp_connection_repo.list_org_scoped(session, organization_id=uuid.uuid4())

        assert "ORDER BY mcp_connections.created_at ASC" in _sql(session)

    async def test_the_total_is_counted_over_the_same_filters_as_the_rows(self):
        rows = [_connection(), _connection()]
        session = _RecordingSession(_Result(scalar=2), _Result(rows=rows))

        items, total = await mcp_connection_repo.list_org_scoped(
            session, organization_id=uuid.uuid4()
        )

        assert (items, total) == (rows, 2)
        assert "org" in set(_filters(session, index=0).values())


class TestGetOrgScopedByName:
    async def test_a_name_is_unique_within_one_organization(self):
        """The name becomes the agent's tool prefix. Two organization servers
        sharing one produce two sets of tools nobody can tell apart, so the
        collision has to be found before the row is written."""
        session = _RecordingSession(_Result(scalar=None))
        organization_id = uuid.uuid4()

        await mcp_connection_repo.get_org_scoped_by_name(
            session, organization_id=organization_id, name="github"
        )

        assert set(_filters(session).values()) == {organization_id, "github", "org"}

    async def test_a_members_personal_server_is_not_a_collision(self):
        """A personal "github" and an organization "github" are different rows
        in different namespaces; treating one as the other's collision would
        refuse a name the organization is entitled to."""
        session = _RecordingSession(_Result(scalar=None))

        await mcp_connection_repo.get_org_scoped_by_name(
            session, organization_id=uuid.uuid4(), name="github"
        )

        assert _filters(session)["scope_1"] == "org"


class TestCreateOrgScoped:
    async def test_the_row_belongs_to_the_organization_and_to_nobody(self):
        """``user_id`` stays NULL and the author goes in ``created_by_user_id``.
        An organization server that carried an owner would be reachable through
        the personal routes, which ask for no organization permission at all -
        and would vanish the day that account was closed."""
        session = _RecordingSession()
        organization_id = uuid.uuid4()
        author_id = uuid.uuid4()

        created = await mcp_connection_repo.create_org_scoped(
            session,
            organization_id=organization_id,
            created_by_user_id=author_id,
            name="linear",
            url="https://mcp.linear.app/sse",
            sealed_token="envelope",
            secret_key_version=2,
            allowed_tools=["search_issues"],
            catalog_key="linear",
            is_enabled=False,
        )

        assert session.added == [created]
        assert (created.user_id, created.created_by_user_id) == (None, author_id)
        assert (created.organization_id, created.scope) == (organization_id, "org")
        assert (created.name, created.url) == ("linear", "https://mcp.linear.app/sse")
        assert (created.auth_token, created.secret_key_version) == ("envelope", 2)
        assert (created.allowed_tools, created.catalog_key) == (["search_issues"], "linear")
        assert (created.is_enabled, created.auth_type) == (False, "bearer")

    async def test_the_row_is_flushed_and_refreshed_but_never_committed(self):
        session = _RecordingSession()

        created = await mcp_connection_repo.create_org_scoped(
            session,
            organization_id=uuid.uuid4(),
            created_by_user_id=uuid.uuid4(),
            name="linear",
            url="https://mcp.linear.app/sse",
            sealed_token=None,
            secret_key_version=1,
            allowed_tools=None,
            catalog_key=None,
        )

        assert (session.flushes, session.refreshed) == (1, [created])


class TestCreate:
    async def test_every_field_the_caller_passed_reaches_the_row(self):
        """The OAuth columns arrive only through this call, and a dropped
        ``oauth_state`` leaves a consent redirect with no row to come back to."""
        session = _RecordingSession()
        user_id = uuid.uuid4()

        created = await mcp_connection_repo.create(
            session,
            user_id=user_id,
            name="linear",
            url="https://mcp.linear.app/sse",
            auth_token="ciphertext",
            secret_key_version=1,
            allowed_tools=["search_issues"],
            is_enabled=False,
            auth_type="oauth",
            oauth_state="state-xyz",
            oauth_payload="live",
            oauth_pending_payload="pending",
        )

        assert session.added == [created]
        assert (created.user_id, created.name, created.url) == (
            user_id,
            "linear",
            "https://mcp.linear.app/sse",
        )
        assert (created.auth_token, created.allowed_tools, created.is_enabled) == (
            "ciphertext",
            ["search_issues"],
            False,
        )
        assert (created.auth_type, created.oauth_state) == ("oauth", "state-xyz")
        assert (created.oauth_payload, created.oauth_pending_payload) == ("live", "pending")

    async def test_the_row_is_flushed_and_refreshed_but_never_committed(self):
        """``get_db_session`` owns the transaction. A repository that commits
        would make the request's later failure unrollbackable - and the caller
        still needs the refresh to see the server-side id and timestamps."""
        session = _RecordingSession()

        created = await mcp_connection_repo.create(
            session,
            user_id=uuid.uuid4(),
            name="github",
            url="https://example.com/mcp",
            auth_token=None,
            secret_key_version=1,
            allowed_tools=None,
        )

        assert session.flushes == 1
        assert session.refreshed == [created]


class TestUpdate:
    async def test_only_the_named_fields_are_written(self):
        """The service passes a partial dict; anything else being touched here
        would silently undo a column the request never mentioned."""
        session = _RecordingSession()
        connection = _connection(name="github", last_status=None)

        updated = await mcp_connection_repo.update(
            session, db_connection=connection, update_data={"last_status": "ok"}
        )

        assert updated is connection
        assert connection.last_status == "ok"
        assert connection.name == "github"
        assert session.flushes == 1


class TestDelete:
    async def test_the_row_is_removed_within_the_callers_transaction(self):
        """Flushed, not committed - deleting a connection is part of the request
        that asked for it and rolls back with it."""
        session = _RecordingSession()
        connection = _connection()

        await mcp_connection_repo.delete(session, db_connection=connection)

        assert session.deleted == [connection]
        assert session.flushes == 1
