"""Tests for the workspace repository - the table holding an agent's files.

Same discipline as the environment and exposure repositories: a repository's
behaviour *is* the statement it builds, so these read the statement back. Here
the predicate that matters most is `organization_id`. The scope key is
unguessable, but "unguessable" is not an access control - dropping the tenant
from a lookup would make one organization's workspace reachable by an id, and
the files in it are whatever somebody uploaded to a chat.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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

    @pytest.mark.security
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

    async def test_an_operator_still_cannot_list_other_peoples_personal_sessions(self):
        organization_id, user_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalars([]))

        await agent_workspace_repo.list_for_reader(
            session, organization_id=organization_id, user_id=user_id, see_all=True
        )

        # Operator access widens ordinary workspace visibility, while personal
        # account files retain their separate owner boundary.
        where = str(session.statements[-1]).split("WHERE", 1)[1]
        assert organization_id in _filters(session).values()
        assert "agent_workspaces.coding_account_id IS NULL" in where
        assert "coding_accounts.user_id" in where
        assert user_id in _filters(session).values()
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
        row = _workspace()
        session = _RecordingSession(None, MagicMock(scalar_one=MagicMock(return_value=row)))
        organization_id, agent_id, conversation_id = (
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
        )

        created = await agent_workspace_repo.create(
            session,
            organization_id=organization_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            owner_ref="U123",
            scope="conversation",
            scope_key="sc-1",
            backend="docker",
        )

        inserted = session.statements[0].compile(dialect=postgresql.dialect())
        assert inserted.params["organization_id"] == organization_id
        assert inserted.params["agent_id"] == agent_id
        assert inserted.params["conversation_id"] == conversation_id
        assert inserted.params["owner_ref"] == "U123"
        assert inserted.params["last_used_at"] is not None
        # Recorded when a session is opened, not when the row is: see `record_session`.
        assert "session_id" not in inserted.params
        # A first open racing another takes the row on the key, whichever wrote it.
        assert "ON CONFLICT ON CONSTRAINT uq_agent_workspace_scope DO NOTHING" in str(inserted)
        assert created is row

    async def test_recording_a_session_sets_it_and_forgetting_clears_it(self):
        session = _RecordingSession()
        row = _workspace()

        await agent_workspace_repo.record_session(session, workspace=row, session_id="xc-1")
        assert row.session_id == "xc-1"
        await agent_workspace_repo.record_session(session, workspace=row, session_id=None)
        assert row.session_id is None

    async def test_saving_bumps_the_version_so_an_overlap_is_visible(self):
        """Two turns of one conversation cannot normally run at once; this is
        how it is *noticed* if they ever do."""
        session = _RecordingSession()
        row = _workspace(version=3)

        saved = await agent_workspace_repo.save_files(
            session, workspace=row, files={"/a.txt": {}}, directories=["/out"], bytes_total=42
        )

        assert saved.version == 4
        assert saved.bytes_total == 42
        assert saved.files == {"/a.txt": {}}
        assert saved.directories == ["/out"]

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


@pytest.mark.security
async def test_project_file_mutations_refresh_the_snapshot_under_a_tenant_scoped_lock() -> None:
    db = _RecordingSession(None)
    organization, project = uuid.uuid4(), uuid.uuid4()
    await agent_workspace_repo.lock_project_files(
        db, project_id=project, organization_id=organization
    )
    statement = db.statements[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert organization in compiled.params.values()
    assert project in compiled.params.values()
    assert "project" in compiled.params.values()
    assert "FOR UPDATE" in str(compiled)
    assert statement.get_execution_options()["populate_existing"] is True


@pytest.mark.security
async def test_project_origin_inventory_keeps_newest_row_and_excludes_unbound_rows() -> None:
    organization_id, project_id = uuid.uuid4(), uuid.uuid4()
    newest, older = _workspace(project_id=project_id), _workspace(project_id=project_id)
    unbound = _workspace(project_id=None)
    session = _RecordingSession(SimpleNamespace(scalars=lambda: [newest, unbound, older]))
    found = await agent_workspace_repo.active_for_projects(
        session, organization_id=organization_id, project_ids=[project_id]
    )
    assert found == {project_id: newest}
    params = _filters(session)
    assert organization_id in params.values()
    assert [project_id] in params.values()


async def test_project_chat_without_active_project_workspace_retains_its_conversation_files() -> (
    None
):
    organization_id, conversation_id, project_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    own = _workspace()
    session = SimpleNamespace(scalar=AsyncMock(return_value=project_id))
    with (
        patch.object(
            agent_workspace_repo, "get_for_project", new=AsyncMock(return_value=None)
        ) as project,
        patch.object(
            agent_workspace_repo, "list_for_conversation", new=AsyncMock(return_value=[own])
        ) as conversation,
    ):
        found = await agent_workspace_repo.kept_for_conversation(
            session, organization_id=organization_id, conversation_id=conversation_id
        )
    assert found is own
    project.assert_awaited_once_with(
        session, organization_id=organization_id, project_id=project_id
    )
    conversation.assert_awaited_once_with(
        session, organization_id=organization_id, conversation_id=conversation_id
    )
