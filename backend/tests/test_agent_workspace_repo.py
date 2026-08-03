"""Tests for the workspace repository - the table holding an agent's files.

Same discipline as the environment and exposure repositories: a repository's
behaviour *is* the statement it builds, so these read the statement back. Here
the predicate that matters most is `organization_id`. The scope key is
unguessable, but "unguessable" is not an access control - dropping the tenant
from a lookup would make one organization's workspace reachable by an id, and
the files in it are whatever somebody uploaded to a chat.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models.agent_workspace import AgentWorkspace
from app.repositories import agent_workspace_repo

pytestmark = pytest.mark.anyio


class _RecordingSession:
    """An `AsyncSession` stand-in that keeps the statements it was given."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.statements: list[object] = []
        self.added: list[AgentWorkspace] = []
        self.deleted: list[AgentWorkspace] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self._results.pop(0)

    def add(self, instance: AgentWorkspace) -> None:
        self.added.append(instance)

    async def delete(self, instance: AgentWorkspace) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        pass

    async def refresh(self, instance: AgentWorkspace) -> None:
        pass


def _filters(session: _RecordingSession) -> dict[str, object]:
    return session.statements[-1].compile(dialect=postgresql.dialect()).params


def _scalar(value: object):
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


def _scalars(values: list[object]):
    return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=values))))


def _workspace(**overrides: object) -> AgentWorkspace:
    row = AgentWorkspace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        scope="conversation",
        scope_key="sc-deadbeef-cafe",
        backend="state",
        bytes_total=0,
        version=0,
    )
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


class TestReading:
    async def test_a_workspace_is_looked_up_inside_its_organization(self):
        """Without the scope, a key from another tenant would resolve."""
        organization_id = uuid.uuid4()
        session = _RecordingSession(_scalar(None))

        await agent_workspace_repo.get_by_key(
            session, organization_id=organization_id, scope_key="sc-1234"
        )

        assert set(_filters(session).values()) >= {organization_id, "sc-1234"}

    async def test_a_workspace_is_looked_up_by_id_inside_its_organization(self):
        """The browser addresses a workspace by its own id - a run-scoped one has
        no conversation and an agent-scoped one belongs to all of them - and an
        unguessable id is not an access control."""
        organization_id, workspace_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalar(None))

        await agent_workspace_repo.get(session, workspace_id, organization_id=organization_id)

        assert set(_filters(session).values()) >= {organization_id, workspace_id}

    async def test_a_conversation_listing_is_scoped_to_the_tenant_too(self):
        organization_id, conversation_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalars([]))

        await agent_workspace_repo.list_for_conversation(
            session, organization_id=organization_id, conversation_id=conversation_id
        )

        assert set(_filters(session).values()) >= {organization_id, conversation_id}

    async def test_an_organization_listing_puts_the_most_recent_first(self):
        """An operator looking at workspaces wants the warm ones, and a
        workspace nothing has opened has a null `last_used_at` to sort past."""
        organization_id = uuid.uuid4()
        session = _RecordingSession(_scalars([]))

        await agent_workspace_repo.list_for_organization(session, organization_id=organization_id)

        statement = str(session.statements[-1])
        assert organization_id in _filters(session).values()
        assert "ORDER BY" in statement
        assert "last_used_at" in statement


class TestWhoAListingIsFor:
    """The predicates that decide whose workspaces come back.

    Read off the statement, because that *is* the behaviour: an operator listing
    and a member's are the same query with one `OR` in it, and the difference
    between them is whether that clause is there at all.
    """

    async def test_an_operator_gets_the_organization_and_nothing_narrower(self):
        organization_id = uuid.uuid4()
        session = _RecordingSession(_scalars([]))

        await agent_workspace_repo.list_for_reader(
            session, organization_id=organization_id, user_id=uuid.uuid4(), see_all=True
        )

        # The model's own columns are in the SELECT either way, so the question is
        # what is in the WHERE: one predicate, the tenant, and no `OR` narrowing it.
        where = str(session.statements[-1]).split("WHERE", 1)[1]
        assert organization_id in _filters(session).values()
        assert " OR " not in where
        assert "last_used_at" in where

    async def test_a_member_gets_their_own_files_their_chats_and_their_agents(self):
        """The three ways a person reaches a workspace, and no fourth."""
        organization_id, user_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalars([]))

        await agent_workspace_repo.list_for_reader(
            session, organization_id=organization_id, user_id=user_id, see_all=False
        )

        where = str(session.statements[-1]).split("WHERE", 1)[1]
        statement = str(session.statements[-1])
        assert "owner_ref" in where
        assert "conversations" in statement
        # Through `messages`, because `agent_id` is on the message rather than the
        # conversation - the picker can be changed mid-thread.
        assert "messages" in statement
        assert str(user_id) in _filters(session).values()

    async def test_channel_scope_is_reachable_only_by_an_operator(self):
        """Its people are identified by Slack or Telegram, not by a row in
        `users`, so no member predicate can name them."""
        session = _RecordingSession(_scalars([]))

        await agent_workspace_repo.list_for_reader(
            session, organization_id=uuid.uuid4(), user_id=uuid.uuid4(), see_all=False
        )

        assert "'channel'" not in str(session.statements[-1])

    async def test_an_anonymous_caller_gets_nothing_rather_than_everything(self):
        """The dangerous direction: a missing subject must narrow the listing to
        nothing, never widen it to the organization."""
        session = _RecordingSession()

        found = await agent_workspace_repo.list_for_reader(
            session, organization_id=uuid.uuid4(), user_id=None, see_all=False
        )

        assert found == []
        assert session.statements == []


class TestWriting:
    async def test_creating_records_who_the_workspace_belongs_to(self):
        session = _RecordingSession()
        organization_id, agent_id, conversation_id = (
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
        )

        await agent_workspace_repo.create(
            session,
            organization_id=organization_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            owner_ref="U123",
            scope="conversation",
            scope_key="sc-1",
            backend="docker",
            session_id="sc-1",
        )

        [created] = session.added
        assert created.organization_id == organization_id
        assert created.agent_id == agent_id
        assert created.conversation_id == conversation_id
        assert created.owner_ref == "U123"
        assert created.session_id == "sc-1"
        assert created.last_used_at is not None

    async def test_saving_bumps_the_version_so_an_overlap_is_visible(self):
        """Two turns of one conversation cannot normally run at once; this is
        how it is *noticed* if they ever do."""
        session = _RecordingSession()
        row = _workspace(version=3)

        saved = await agent_workspace_repo.save_files(
            session, workspace=row, files={"/a.txt": {}}, bytes_total=42
        )

        assert saved.version == 4
        assert saved.bytes_total == 42
        assert saved.files == {"/a.txt": {}}

    async def test_touching_records_use_without_changing_the_files(self):
        session = _RecordingSession()
        row = _workspace(files={"/a.txt": {}}, version=2)

        touched = await agent_workspace_repo.touch(session, workspace=row)

        assert touched.last_used_at is not None
        assert touched.version == 2
        assert touched.files == {"/a.txt": {}}

    async def test_deleting_removes_the_row(self):
        session = _RecordingSession()
        row = _workspace()

        await agent_workspace_repo.delete(session, workspace=row)

        assert session.deleted == [row]
