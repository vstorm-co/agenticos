"""The workspace an agent works in: who shares it, and what it refuses.

Most of this platform's value is in what it refuses, and a workspace has three
refusals worth more than the feature itself:

* a run in one organization cannot reach another organization's files;
* a scope the run cannot key is refused by name rather than falling back to a
  broader one, because the fallback would merge strangers' workspaces silently;
* a write past the storage ceiling is rejected with a message the model reads,
  rather than accepted and dropped in a `finally` block.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic_ai_backends import StateBackend

from app.agents.capabilities import build as build_capabilities
from app.agents.capabilities import get as get_capability
from app.agents.capabilities._registry import CapabilityBinding
from app.agents.capabilities.approval import approval_required_tools
from app.agents.capabilities.sandbox import SandboxConfig
from app.agents.capabilities.sandbox._capped import CappedStateBackend, document_size
from app.agents.capabilities.sandbox._identity import (
    MAX_SESSION_ID,
    WorkspaceIdentity,
    WorkspaceScopeUnavailable,
    scope_key,
)
from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.repositories import agent_workspace as workspace_repo
from app.services.sandbox_connection import ResolvedConnection, SandboxConnectionService
from app.services.sandbox_workspace import SandboxWorkspaceService, sandbox_config

pytestmark = pytest.mark.anyio


def _ctx(organization_id: UUID | None = None) -> AuthContext:
    return AuthContext(
        user_id=uuid4(),
        organization_id=organization_id or uuid4(),
        role=OrgRoleName.OWNER,
    )


def _identity(**overrides: object) -> WorkspaceIdentity:
    defaults: dict[str, object] = {
        "organization_id": uuid4(),
        "agent_id": uuid4(),
        "run_id": uuid4(),
        "conversation_id": uuid4(),
        "user_id": "user-1",
    }
    return WorkspaceIdentity(**{**defaults, **overrides})  # type: ignore[arg-type]


def _spec(**config: object) -> AgentSpec:
    return AgentSpec(
        name="Analyst",
        capabilities=[{"id": "sandbox", "config": config}],
    )


def _resolved(
    *,
    kind: str = "docker",
    base_url: str | None = "http://sandboxd:8080",
    default_runtime: str | None = None,
    token: str = "service-token",
) -> ResolvedConnection:
    """A registered connection with its credential already unsealed.

    Where a sandbox runs is a row now, not a setting, so every container-backed
    test resolves one. The vault half is exercised in `tests/test_secrets.py`
    and the resolution half in `tests/test_sandbox_connections.py`; here the
    question is only what the workspace service does with the answer.
    """
    row = MagicMock()
    row.id = uuid4()
    row.kind = kind
    row.base_url = base_url
    row.default_runtime = default_runtime
    row.name = "Local Docker"
    return ResolvedConnection(row=row, token=token)


def _serve(monkeypatch, resolved: ResolvedConnection | Exception) -> None:
    async def _resolve(self, ctx, connection_id):
        if isinstance(resolved, Exception):
            raise resolved
        return resolved

    monkeypatch.setattr(SandboxConnectionService, "resolve", _resolve)


class _ClosesItsClient:
    """Base for the archive fakes below, giving them the method the real one has.

    `WorkspaceArchive` builds and owns an `httpx.Client` unless it is handed one,
    and `close()` is what releases it. Every fake here was a bare class without the
    method, so nothing in this file could tell a closed client from an abandoned
    one - which is how `_archive` came to leak a connection pool on every read
    while the coverage report read as complete. Inheriting it means a fake that
    would break if the service stopped closing.
    """

    closed = False

    def close(self) -> None:
        self.closed = True


class TestWhoSharesAWorkspace:
    def test_two_organizations_never_share_a_key(self):
        """The refusal this whole feature is measured against."""
        conversation = uuid4()
        agent = uuid4()
        first = _identity(organization_id=uuid4(), agent_id=agent, conversation_id=conversation)
        second = _identity(organization_id=uuid4(), agent_id=agent, conversation_id=conversation)

        assert scope_key(first, "conversation", "state") != scope_key(
            second, "conversation", "state"
        )

    def test_the_same_conversation_returns_to_the_same_workspace(self):
        identity = _identity()

        assert scope_key(identity, "conversation", "state") == scope_key(
            _identity(
                organization_id=identity.organization_id,
                agent_id=identity.agent_id,
                conversation_id=identity.conversation_id,
                run_id=uuid4(),
            ),
            "conversation",
            "state",
        )

    def test_a_run_scoped_workspace_is_new_every_turn(self):
        identity = _identity()
        next_turn = _identity(
            organization_id=identity.organization_id,
            agent_id=identity.agent_id,
            conversation_id=identity.conversation_id,
        )

        assert scope_key(identity, "run", "state") != scope_key(next_turn, "run", "state")

    def test_a_user_workspace_is_per_agent(self):
        """Files gathered for one agent are not another agent's to read."""
        organization = uuid4()
        first = _identity(organization_id=organization, agent_id=uuid4())
        second = _identity(organization_id=organization, agent_id=uuid4())

        assert scope_key(first, "user", "state") != scope_key(second, "user", "state")

    def test_two_user_ids_differing_only_in_punctuation_do_not_collide(self):
        """Sanitising instead of hashing mapped `a.b` and `ab` onto one workspace."""
        agent, organization = uuid4(), uuid4()
        dotted = _identity(organization_id=organization, agent_id=agent, user_id="a.b")
        plain = _identity(organization_id=organization, agent_id=agent, user_id="ab")

        assert scope_key(dotted, "user", "state") != scope_key(plain, "user", "state")

    def test_changing_the_backend_does_not_reattach_to_the_old_workspace(self):
        """A stored document and a container's volume are not the same thing."""
        identity = _identity()

        assert scope_key(identity, "conversation", "state") != scope_key(
            identity, "conversation", "service"
        )

    @pytest.mark.parametrize("scope", ["run", "conversation", "channel", "user", "agent"])
    def test_every_key_fits_what_the_service_accepts(self, scope: str):
        """`sandboxd` rejects an id over 64 characters, on the first tool call."""
        identity = _identity(user_id="U" * 200, channel_key="C" * 200)

        assert len(scope_key(identity, scope, "service")) <= MAX_SESSION_ID  # type: ignore[arg-type]

    def test_a_conversation_scope_with_no_conversation_is_refused(self):
        with pytest.raises(WorkspaceScopeUnavailable):
            scope_key(_identity(conversation_id=None), "conversation", "state")

    def test_a_user_scope_with_no_user_is_refused(self):
        """Rather than falling back and merging strangers' files."""
        with pytest.raises(WorkspaceScopeUnavailable):
            scope_key(_identity(user_id=None), "user", "state")

    def test_a_channel_scope_in_web_chat_is_refused_by_name(self):
        """There is no channel above a web conversation. Falling back to the
        conversation would look like it worked and quietly mean something else."""
        with pytest.raises(WorkspaceScopeUnavailable) as refused:
            scope_key(_identity(channel_key=None), "channel", "state")

        assert "messaging channel" in str(refused.value)

    def test_two_agents_in_one_channel_do_not_share_a_workspace(self):
        """Putting both bots in a room is not a request that either read the
        other's files."""
        organization = uuid4()
        first = _identity(organization_id=organization, agent_id=uuid4(), channel_key="C123")
        second = _identity(organization_id=organization, agent_id=uuid4(), channel_key="C123")

        assert scope_key(first, "channel", "state") != scope_key(second, "channel", "state")

    def test_threads_in_one_channel_share_it(self):
        """The reason `channel` exists: `conversation` scope on Slack is one
        workspace per thread, which is fifty containers in a busy channel."""
        agent, organization = uuid4(), uuid4()
        first = _identity(
            organization_id=organization,
            agent_id=agent,
            conversation_id=uuid4(),
            channel_key="C123",
        )
        second = _identity(
            organization_id=organization,
            agent_id=agent,
            conversation_id=uuid4(),
            channel_key="C123",
        )

        assert scope_key(first, "channel", "state") == scope_key(second, "channel", "state")


class TestTheStorageCeiling:
    def test_a_write_past_the_ceiling_is_refused_and_rolled_back(self):
        backend = CappedStateBackend(StateBackend(), max_bytes=400)
        backend.write("/keep.txt", "hello")

        result = backend.write("/huge.txt", "x" * 5000)

        assert result.error is not None
        assert "workspace is full" in result.error
        assert backend.exists("/keep.txt")
        assert not backend.exists("/huge.txt")

    def test_an_edit_past_the_ceiling_leaves_the_file_as_it_was(self):
        backend = CappedStateBackend(StateBackend(), max_bytes=400)
        backend.write("/notes.txt", "hello")

        result = backend.edit("/notes.txt", "hello", "y" * 5000)

        assert result.error is not None
        assert "hello" in backend.read("/notes.txt")

    def test_an_edit_inside_the_ceiling_goes_through(self):
        backend = CappedStateBackend(StateBackend(), max_bytes=4096)
        backend.write("/notes.txt", "hello world")

        result = backend.edit("/notes.txt", "world", "there")

        assert result.error is None
        assert result.occurrences == 1
        assert "hello there" in backend.read("/notes.txt")

    def test_a_failing_write_is_reported_rather_than_measured(self):
        """A path the backend rejects never reaches the ceiling check."""
        backend = CappedStateBackend(StateBackend(), max_bytes=400)

        result = backend.write("../escape.txt", "x")

        assert result.error is not None
        assert "workspace is full" not in result.error

    def test_an_edit_of_a_missing_file_is_reported_unchanged(self):
        backend = CappedStateBackend(StateBackend(), max_bytes=400)

        result = backend.edit("/nothing.txt", "a", "b")

        assert result.error is not None
        assert "not found" in result.error

    def test_the_read_side_is_delegated_untouched(self):
        backend = CappedStateBackend(StateBackend(), max_bytes=4096)
        backend.write("/src/app.py", "print('hi')\nprint('there')")

        assert backend.exists("/src/app.py")
        assert [entry["name"] for entry in backend.ls_info("/src")] == ["app.py"]
        assert backend.read_bytes("/src/app.py").startswith(b"print")
        assert "print" in backend.read("/src/app.py")
        assert [entry["name"] for entry in backend.glob_info("**/*.py")] == ["app.py"]
        assert backend.grep_raw("there")
        assert "CappedStateBackend" in repr(backend)

    def test_size_is_measured_as_the_document_that_gets_stored(self):
        backend = StateBackend()
        backend.write("/a.txt", "x")

        assert document_size(backend.files) > 0


class TestReadingTheSpec:
    def test_an_agent_without_the_capability_has_no_workspace(self):
        assert sandbox_config(AgentSpec(name="Plain")) is None

    def test_a_disabled_binding_is_no_workspace(self):
        spec = AgentSpec(
            name="Off", capabilities=[{"id": "sandbox", "config": {}, "enabled": False}]
        )

        assert sandbox_config(spec) is None

    def test_the_defaults_are_the_ones_every_deployment_can_run(self):
        config = sandbox_config(_spec())

        assert config == SandboxConfig(backend="state", session_scope="conversation")


class TestApprovalIsPerTool:
    def test_only_running_commands_is_gated(self):
        """One flag for the capability would gate `ls`, and authors would turn the
        lot off rather than write seven overrides.

        Writing is not gated either, which was a correction rather than a default:
        a workspace is scratch space deleted with its conversation, so a write is
        not the class of act an email is - and an agent that must ask before every
        one cannot do multi-step work, which is how an author ends up turning off
        the gate that mattered. `execute` runs arbitrary commands on somebody's
        host, and that is the one worth a person looking at.
        """
        gated = approval_required_tools(_spec())

        assert gated == {"execute"}

    def test_a_binding_still_overrides_the_code(self):
        spec = AgentSpec(
            name="Careful",
            capabilities=[
                {"id": "sandbox", "config": {}, "tool_approval": {"read_file": "required"}}
            ],
        )

        assert "read_file" in approval_required_tools(spec)

    def test_renaming_a_tool_keeps_its_gate(self):
        """The failure this is guarding: a renamed `execute` running unattended."""
        spec = AgentSpec(
            name="Renamed",
            capabilities=[
                {"id": "sandbox", "config": {}, "tool_overrides": {"execute": {"name": "run_it"}}}
            ],
        )

        gated = approval_required_tools(spec)

        assert "run_it" in gated
        assert "execute" not in gated


class TestBuildingTheCapability:
    def test_without_a_backend_the_workspace_is_in_memory(self):
        """A preview has nowhere durable to write, which is not an error."""
        built = build_capabilities([CapabilityBinding(capability_id="sandbox")])

        toolset = built[0].get_toolset()

        assert toolset is not None
        assert "write_file" in toolset.tools

    def test_turning_the_shell_off_removes_it_rather_than_gating_it(self):
        built = build_capabilities(
            [CapabilityBinding(capability_id="sandbox", config={"include_execute": False})]
        )

        toolset = built[0].get_toolset()

        assert toolset is not None
        assert "execute" not in toolset.tools

    def test_the_catalog_and_the_model_read_the_same_description(self):
        """Two copies in two repositories drift, and nothing reports it."""
        definition = get_capability("sandbox")
        built = build_capabilities([CapabilityBinding(capability_id="sandbox")])
        toolset = built[0].get_toolset()

        assert toolset is not None
        for tool in definition.tools:
            assert toolset.tools[tool.id].tool_def.description == tool.description

    def test_the_background_shells_are_not_offered(self):
        built = build_capabilities([CapabilityBinding(capability_id="sandbox")])
        toolset = built[0].get_toolset()

        assert toolset is not None
        assert "run_in_background" not in toolset.tools

    def test_no_backend_demands_a_credential_on_the_binding(self):
        """The credential moved to the connection, and that is the point.

        A key on a capability binding is a key per agent; a sandbox credential
        authorises running commands on a host, which is a property of the host
        rather than of whoever happens to be pointed at it. Leaving the old
        requirement in place would have asked every author for a token they have
        no business holding.
        """
        definition = get_capability("sandbox")

        assert not definition.needs_secret(SandboxConfig(backend="state"))
        assert not definition.needs_secret(SandboxConfig(backend="service"))


class TestOpeningAndClosing:
    async def test_an_agent_without_a_workspace_opens_nothing(self, mock_db_session):
        service = SandboxWorkspaceService(mock_db_session)

        assert await service.open(AgentSpec(name="Plain"), ctx=_ctx(), identity=_identity()) is None

    async def test_a_run_scoped_state_workspace_needs_no_row(self, monkeypatch, mock_db_session):
        created = AsyncMock()
        monkeypatch.setattr(workspace_repo, "create", created)
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(session_scope="run"), ctx=_ctx(), identity=_identity())

        assert workspace is not None
        assert workspace.row_id is None
        created.assert_not_called()

    async def test_a_stored_document_comes_back_on_the_next_turn(
        self, monkeypatch, mock_db_session
    ):
        stored = StateBackend()
        stored.write("/report.md", "the numbers")
        row = _row(files=dict(stored.files))
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=row))
        monkeypatch.setattr(workspace_repo, "touch", AsyncMock(return_value=row))
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(), ctx=_ctx(), identity=_identity())

        assert workspace is not None
        assert "the numbers" in workspace.backend.read("/report.md")

    async def test_closing_stores_what_the_run_wrote(self, monkeypatch, mock_db_session):
        row = _row()
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        monkeypatch.setattr(workspace_repo, "create", AsyncMock(return_value=row))
        saved = AsyncMock(return_value=row)
        monkeypatch.setattr(workspace_repo, "save_files", saved)
        mock_db_session.get = AsyncMock(return_value=row)
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(), ctx=_ctx(), identity=_identity())
        assert workspace is not None
        workspace.backend.write("/notes.txt", "kept")
        await service.close(workspace)

        assert "/notes.txt" in saved.await_args.kwargs["files"]
        assert saved.await_args.kwargs["bytes_total"] > 0

    async def test_closing_nothing_is_not_an_error(self, mock_db_session):
        await SandboxWorkspaceService(mock_db_session).close(None)

    async def test_a_flush_overtaken_by_another_run_says_which_paths_it_dropped(
        self, monkeypatch, mock_db_session, caplog
    ):
        """The last flush wins, and this is what stops it winning silently.

        Reachable under the scopes whose purpose is sharing - `agent`, `channel`,
        `user` - where two runs hold one workspace and the socket's own guard does
        not apply. `version` documented this detection long before anything read
        the column.
        """
        opened = _row(version=4)
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=opened))
        monkeypatch.setattr(workspace_repo, "touch", AsyncMock(return_value=opened))
        monkeypatch.setattr(workspace_repo, "save_files", AsyncMock(return_value=opened))
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(
            _spec(session_scope="agent"), ctx=_ctx(), identity=_identity()
        )
        assert workspace is not None
        workspace.backend.write("/mine.txt", "this run's work")
        # Somebody else finished in between: the committed row has moved on, and
        # holds a file this run never saw.
        overtaken = _row(version=5, files={"/theirs.txt": {"content": ["gone"]}})
        mock_db_session.get = AsyncMock(return_value=overtaken)

        with caplog.at_level(logging.WARNING):
            await service.close(workspace)

        [record] = [r for r in caplog.records if r.message == "workspace_flush_overtaken"]
        assert record.opened_version == 4
        assert record.found_version == 5
        assert record.paths_lost == ["/theirs.txt"]
        assert record.scope == "agent"

    async def test_an_uncontested_flush_says_nothing(self, monkeypatch, mock_db_session, caplog):
        """The log is for the race, so an ordinary turn must not produce one -
        otherwise the line means nothing when it matters."""
        row = _row(version=4)
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=row))
        monkeypatch.setattr(workspace_repo, "touch", AsyncMock(return_value=row))
        monkeypatch.setattr(workspace_repo, "save_files", AsyncMock(return_value=row))
        mock_db_session.get = AsyncMock(return_value=_row(version=4))
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(), ctx=_ctx(), identity=_identity())
        assert workspace is not None
        workspace.backend.write("/mine.txt", "work")

        with caplog.at_level(logging.WARNING):
            await service.close(workspace)

        assert not [r for r in caplog.records if r.message == "workspace_flush_overtaken"]

    async def test_the_committed_row_is_read_rather_than_the_one_already_loaded(
        self, monkeypatch, mock_db_session
    ):
        """`populate_existing`, or the identity map answers with the row as it was
        at `open` and another session's commit is invisible by construction."""
        row = _row(version=1)
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=row))
        monkeypatch.setattr(workspace_repo, "touch", AsyncMock(return_value=row))
        monkeypatch.setattr(workspace_repo, "save_files", AsyncMock(return_value=row))
        mock_db_session.get = AsyncMock(return_value=row)
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(), ctx=_ctx(), identity=_identity())
        await service.close(workspace)

        assert mock_db_session.get.await_args.kwargs["populate_existing"] is True

    async def test_a_run_scoped_state_workspace_is_not_stored(self, monkeypatch, mock_db_session):
        """It has no row by design, so there is nowhere for it to persist to -
        which is exactly what "a fresh workspace every turn" means."""
        saved = AsyncMock()
        monkeypatch.setattr(workspace_repo, "save_files", saved)
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(session_scope="run"), ctx=_ctx(), identity=_identity())
        assert workspace is not None
        workspace.backend.write("/scratch.txt", "gone after this")
        await service.close(workspace)

        saved.assert_not_called()

    async def test_a_conversation_deleted_mid_run_loses_its_files(
        self, monkeypatch, mock_db_session
    ):
        """The files belonged to it; keeping them would outlive the thread."""
        row = _row()
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        monkeypatch.setattr(workspace_repo, "create", AsyncMock(return_value=row))
        saved = AsyncMock()
        monkeypatch.setattr(workspace_repo, "save_files", saved)
        mock_db_session.get = AsyncMock(return_value=None)
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(), ctx=_ctx(), identity=_identity())
        await service.close(workspace)

        saved.assert_not_called()

    async def test_a_storage_failure_does_not_replace_the_run_s_own_outcome(
        self, monkeypatch, mock_db_session
    ):
        """`close` runs in the same `finally` that records what the run cost."""
        row = _row()
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        monkeypatch.setattr(workspace_repo, "create", AsyncMock(return_value=row))
        monkeypatch.setattr(
            workspace_repo, "save_files", AsyncMock(side_effect=RuntimeError("database gone"))
        )
        mock_db_session.get = AsyncMock(return_value=row)
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(), ctx=_ctx(), identity=_identity())

        await service.close(workspace)

    async def test_a_scope_this_run_cannot_key_is_refused_by_name(self, mock_db_session):
        service = SandboxWorkspaceService(mock_db_session)

        with pytest.raises(BadRequestError) as exc:
            await service.open(
                _spec(session_scope="user"), ctx=_ctx(), identity=_identity(user_id=None)
            )

        assert "no signed-in user" in exc.value.message

    async def test_a_connection_that_no_longer_resolves_is_refused_where_it_is_read(
        self, monkeypatch, mock_db_session
    ):
        """A spec valid at publish can stop being valid: a host is retired, a key
        is rotated out of the vault. The refusal has to name which, because the
        reader here is a user in a conversation and the fix is elsewhere."""
        _serve(monkeypatch, BadRequestError(message="The sandbox connection 'Big box' is gone"))
        service = SandboxWorkspaceService(mock_db_session)

        with pytest.raises(BadRequestError) as exc:
            await service.open(_spec(backend="service"), ctx=_ctx(), identity=_identity())

        assert "Big box" in exc.value.message


def _no_conversations(monkeypatch) -> None:
    """No titles and no counts, for a listing test that is about something else."""
    from app.repositories import conversation as conversation_repo

    monkeypatch.setattr(conversation_repo, "titles_for", AsyncMock(return_value={}))
    monkeypatch.setattr(conversation_repo, "count_by_agent", AsyncMock(return_value={}))


def _member_ctx() -> AuthContext:
    """A caller who holds no `connections:manage`, which is most people."""
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.MEMBER)


def _row(**overrides: object):
    from app.db.models.agent_workspace import AgentWorkspace

    row = AgentWorkspace(
        id=uuid4(),
        organization_id=uuid4(),
        agent_id=uuid4(),
        scope="conversation",
        scope_key="sc-deadbeef-cafe",
        backend="state",
        files=None,
        bytes_total=0,
        version=0,
    )
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


class TestWorkspacesAreScopedToTheirReader:
    """Who sees which workspace, and why the route carries no gate.

    The gate this replaced refused a member outright, which made a listing of a
    person's *own* files an operator screen. The narrowing moved into the query, so
    what is worth proving here is that it is applied - to the listing, and to a
    workspace fetched by id, where a hidden row served by id is not access control
    at all.
    """

    async def test_an_operator_sees_the_organizations_workspaces(
        self, monkeypatch, mock_db_session
    ):
        from app.repositories import agent as agent_repo

        listed = AsyncMock(return_value=[])
        monkeypatch.setattr(workspace_repo, "list_for_reader", listed)
        monkeypatch.setattr(agent_repo, "get_many", AsyncMock(return_value={}))

        await SandboxWorkspaceService(mock_db_session).visible_to(_ctx())

        assert listed.await_args.kwargs["see_all"] is True

    async def test_a_member_sees_only_what_they_are_part_of(self, monkeypatch, mock_db_session):
        """Their own user-scoped files, their own conversations, and the shared
        workspace of an agent they have talked to - not the organization's."""
        from app.repositories import agent as agent_repo

        listed = AsyncMock(return_value=[])
        monkeypatch.setattr(workspace_repo, "list_for_reader", listed)
        monkeypatch.setattr(agent_repo, "get_many", AsyncMock(return_value={}))
        ctx = _member_ctx()

        await SandboxWorkspaceService(mock_db_session).visible_to(ctx)

        assert listed.await_args.kwargs == {
            "organization_id": ctx.organization_id,
            "user_id": ctx.user_id,
            "see_all": False,
        }

    async def test_a_member_reading_a_workspace_they_cannot_see_is_told_it_is_missing(
        self, monkeypatch, mock_db_session
    ):
        """Not "forbidden": an id must not be usable to find out which workspaces
        exist in a colleague's conversation."""
        row = _row()
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))
        monkeypatch.setattr(workspace_repo, "list_for_reader", AsyncMock(return_value=[]))

        with pytest.raises(NotFoundError):
            await SandboxWorkspaceService(mock_db_session).files_of(_member_ctx(), row.id)

    async def test_a_member_reading_their_own_workspace_gets_it(self, monkeypatch, mock_db_session):
        row = _row(files={})
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))
        monkeypatch.setattr(workspace_repo, "list_for_reader", AsyncMock(return_value=[row]))

        found, _entries = await SandboxWorkspaceService(mock_db_session).files_of(
            _member_ctx(), row.id
        )

        assert found is row

    async def test_an_operator_is_not_asked_a_second_question(self, monkeypatch, mock_db_session):
        """`connections:manage` already answers it, and the visibility query is the
        expensive half."""
        row = _row(files={})
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))
        listed = AsyncMock(return_value=[])
        monkeypatch.setattr(workspace_repo, "list_for_reader", listed)

        await SandboxWorkspaceService(mock_db_session).files_of(_ctx(), row.id)

        listed.assert_not_called()


class TestListingAStoredWorkspace:
    """What "what the agent is keeping" has to include.

    `glob_info("**/*")` does not match a name beginning with a dot, so every listing
    on this branch quietly omitted `.env` and `.gitignore` while `read` served them.
    A listing that claims to be the whole workspace cannot drop a class of filename.
    """

    def test_a_dotfile_is_listed(self):
        from app.services.sandbox_workspace import stored_entries

        stored = StateBackend()
        stored.write("/.env", "A=1")
        stored.write("/notes.md", "x")

        assert [str(entry["path"]) for entry in stored_entries(dict(stored.files))] == [
            "/.env",
            "/notes.md",
        ]

    def test_a_dotfile_in_a_subdirectory_is_listed_too(self):
        from app.services.sandbox_workspace import stored_entries

        stored = StateBackend()
        stored.write("/skills/refunds/.keep", "")

        assert [str(entry["path"]) for entry in stored_entries(dict(stored.files))] == [
            "/skills/refunds/.keep"
        ]

    def test_nothing_is_listed_twice_when_both_patterns_match(self):
        from app.services.sandbox_workspace import stored_entries

        stored = StateBackend()
        stored.write("/report.csv", "a,b")

        assert len(stored_entries(dict(stored.files))) == 1

    def test_a_file_inside_a_dot_directory_stays_out(self):
        """The one omission worth keeping: an agent that ran `git init` would
        otherwise fill the panel with object files nobody asked to see."""
        from app.services.sandbox_workspace import stored_entries

        stored = StateBackend()
        stored.write("/.git/config", "[core]")
        stored.write("/notes.md", "x")

        assert [str(entry["path"]) for entry in stored_entries(dict(stored.files))] == ["/notes.md"]


class TestServingAFileAsBytes:
    """Downloads and image previews, and why text is not enough.

    A chart is the commonest thing a workspace holds that nobody can read as a
    string, and a PNG decoded as UTF-8 and re-encoded is a corrupt PNG. So this path
    exists, and its one refusal is the honest one: a container-backed workspace is
    read through an archive whose only reader is textual.
    """

    async def test_a_stored_file_comes_back_as_the_bytes_it_was_written_as(
        self, monkeypatch, mock_db_session
    ):
        stored = StateBackend()
        stored.write("/report.csv", "month,total")
        row = _row(files=dict(stored.files))
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))

        data = await SandboxWorkspaceService(mock_db_session).read_bytes_of(
            _ctx(), row.id, path="/report.csv"
        )

        assert data == b"month,total"

    async def test_a_path_that_is_not_there_is_missing_rather_than_empty(
        self, monkeypatch, mock_db_session
    ):
        row = _row(files={})
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))

        with pytest.raises(NotFoundError):
            await SandboxWorkspaceService(mock_db_session).read_bytes_of(
                _ctx(), row.id, path="/nope.png"
            )

    async def test_a_text_file_on_a_container_host_is_served(self, monkeypatch, mock_db_session):
        from pydantic_ai_backends import remote as remote_module

        class _Archive(_ClosesItsClient):
            def __init__(self, url, token=""):
                pass

            def ls(self, session_id):
                return []

            def read(self, session_id, path):
                return "print(1)"

        monkeypatch.setattr(remote_module, "WorkspaceArchive", _Archive, raising=False)
        _serve(monkeypatch, _resolved())
        row = _row(backend="service", session_id="dc-1", connection_id=uuid4())
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))

        data = await SandboxWorkspaceService(mock_db_session).read_bytes_of(
            _ctx(), row.id, path="/run.py"
        )

        assert data == b"print(1)"

    async def test_a_binary_on_a_container_host_is_refused_rather_than_mangled(
        self, monkeypatch, mock_db_session
    ):
        """The archive reads text only, and a PNG that has been through `str` is a
        corrupt PNG that downloads successfully - the worst of the three outcomes."""
        row = _row(backend="service", session_id="dc-1", connection_id=uuid4())
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))
        service = SandboxWorkspaceService(mock_db_session)
        service.connections = MagicMock(resolve=AsyncMock(return_value=_resolved()))

        with pytest.raises(BadRequestError) as refused:
            await service.read_bytes_of(_ctx(), row.id, path="/chart.png")

        assert "can only read text" in refused.value.message

    async def test_a_text_file_a_container_host_does_not_have_is_missing(
        self, monkeypatch, mock_db_session
    ):
        row = _row(backend="service", session_id="dc-1", connection_id=None)
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))

        with pytest.raises(NotFoundError):
            await SandboxWorkspaceService(mock_db_session).read_bytes_of(
                _ctx(), row.id, path="/run.py"
            )

    async def test_a_workspace_that_is_not_this_callers_is_missing(
        self, monkeypatch, mock_db_session
    ):
        """The same predicate the listing applies - a download must not be the way
        around it."""
        row = _row(files={})
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))
        monkeypatch.setattr(workspace_repo, "list_for_reader", AsyncMock(return_value=[]))

        with pytest.raises(NotFoundError):
            await SandboxWorkspaceService(mock_db_session).read_bytes_of(
                _member_ctx(), row.id, path="/a.txt"
            )

    async def test_a_path_the_listing_does_not_have_is_missing_rather_than_a_refusal(
        self, monkeypatch, mock_db_session
    ):
        """A container-backed host raises the same way for "no such file" as for
        "this host cannot be read", so the listing answers first - 400 is the wrong
        reply to a typo in a path."""
        from pydantic_ai_backends import remote as remote_module

        class _Archive(_ClosesItsClient):
            def __init__(self, url, token=""):
                pass

            def ls(self, session_id):
                return [{"path": "/run.py", "size": 8, "is_dir": False}]

            def read(self, session_id, path):
                raise AssertionError("the listing should have answered first")

        monkeypatch.setattr(remote_module, "WorkspaceArchive", _Archive, raising=False)
        _serve(monkeypatch, _resolved())
        row = _row(backend="service", session_id="dc-1", connection_id=uuid4())
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))

        with pytest.raises(NotFoundError):
            await SandboxWorkspaceService(mock_db_session).read_bytes_of(
                _ctx(), row.id, path="/typo.py"
            )

    async def test_a_listing_that_could_not_be_read_does_not_claim_a_file_is_missing(
        self, monkeypatch, mock_db_session
    ):
        """It knows nothing, and "no such file" on the strength of a failed listing
        is a confident wrong answer."""
        from pydantic_ai_backends import remote as remote_module

        class _Archive(_ClosesItsClient):
            def __init__(self, url, token=""):
                pass

            def ls(self, session_id):
                raise RuntimeError("This service keeps no workspaces on disk.")

            def read(self, session_id, path):
                raise RuntimeError("This service keeps no workspaces on disk.")

        monkeypatch.setattr(remote_module, "WorkspaceArchive", _Archive, raising=False)
        _serve(monkeypatch, _resolved())
        row = _row(backend="service", session_id="dc-1", connection_id=uuid4())
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))

        with pytest.raises(BadRequestError) as refused:
            await SandboxWorkspaceService(mock_db_session).read_bytes_of(
                _ctx(), row.id, path="/run.py"
            )

        assert "could not be read" in refused.value.message

    async def test_a_dotfile_is_readable_even_though_no_pattern_lists_it(
        self, monkeypatch, mock_db_session
    ):
        """`glob_info("**/*")` does not match a leading dot, so using a *listing* as
        an existence oracle answered "no such file" for a file that reads fine. A
        stored workspace has a real oracle - `exists` - and that is what decides."""
        stored = StateBackend()
        stored.write("/.env", "OPENAI_API_KEY=sk-x")
        row = _row(files=dict(stored.files))
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))

        data = await SandboxWorkspaceService(mock_db_session).read_bytes_of(
            _ctx(), row.id, path="/.env"
        )

        assert data == b"OPENAI_API_KEY=sk-x"

    def test_a_file_with_no_suffix_is_not_assumed_to_be_text(self):
        """Guessing wrong here is silent, and the file that has no suffix is exactly
        where a guess is least informed."""
        from app.services.sandbox_workspace import _is_textual

        assert _is_textual("/notes.md") is True
        assert _is_textual("/Makefile") is False
        assert _is_textual("/chart.PNG") is False


class TestServingAConversationsFileAsBytes:
    """The same bytes, addressed through the chat rather than the workspace row.

    Both entry points exist because they admit different callers: this one is reached
    after the conversation has been fetched, which somebody the chat was *shared*
    with passes, and `read_bytes_of` matches the workspaces a caller owns. Everything
    after the address is shared, so a file that downloads from the Workspaces screen
    cannot be refused in the chat panel.
    """

    async def test_the_bytes_come_back(self, monkeypatch, mock_db_session):
        stored = StateBackend()
        stored.write("/report.csv", "month,total")
        row = _row(files=dict(stored.files))
        monkeypatch.setattr(workspace_repo, "list_for_conversation", AsyncMock(return_value=[row]))

        data = await SandboxWorkspaceService(mock_db_session).read_bytes(
            _ctx(), conversation_id=uuid4(), path="/report.csv"
        )

        assert data == b"month,total"

    async def test_a_chat_with_no_workspace_is_missing_rather_than_empty_bytes(
        self, monkeypatch, mock_db_session
    ):
        """An empty body would be indistinguishable from a file the agent wrote and
        left empty."""
        monkeypatch.setattr(workspace_repo, "list_for_conversation", AsyncMock(return_value=[]))

        with pytest.raises(NotFoundError):
            await SandboxWorkspaceService(mock_db_session).read_bytes(
                _ctx(), conversation_id=uuid4(), path="/report.csv"
            )

    async def test_the_container_limit_is_the_same_one(self, monkeypatch, mock_db_session):
        """Stated once, in the shared half: the archive reads text only, whichever
        way the workspace was addressed."""
        row = _row(backend="service", session_id="dc-1", connection_id=uuid4())
        monkeypatch.setattr(workspace_repo, "list_for_conversation", AsyncMock(return_value=[row]))
        service = SandboxWorkspaceService(mock_db_session)
        service.connections = MagicMock(resolve=AsyncMock(return_value=_resolved()))

        with pytest.raises(BadRequestError) as refused:
            await service.read_bytes(_ctx(), conversation_id=uuid4(), path="/chart.png")

        assert "can only read text" in refused.value.message


class TestOneFlatListOfFiles:
    """The "which agent is holding a copy of that CSV" view.

    What it owes a reader is that a short answer is never mistaken for a small
    number of files: it is bounded, one host can fail, and both of those are in the
    answer rather than in a log line.
    """

    async def test_every_visible_workspaces_files_arrive_in_one_list(
        self, monkeypatch, mock_db_session
    ):
        from app.repositories import agent as agent_repo

        first = StateBackend()
        first.write("/report.csv", "month,total")
        second = StateBackend()
        second.write("/notes.md", "hello")
        monkeypatch.setattr(
            workspace_repo,
            "list_for_reader",
            AsyncMock(return_value=[_row(files=dict(first.files)), _row(files=dict(second.files))]),
        )
        monkeypatch.setattr(agent_repo, "get_many", AsyncMock(return_value={}))
        _no_conversations(monkeypatch)

        listing = await SandboxWorkspaceService(mock_db_session).flat_files(_ctx())

        assert sorted(str(entry.get("path")) for _overview, entry in listing.files) == [
            "/notes.md",
            "/report.csv",
        ]
        assert listing.truncated is False

    async def test_directories_are_not_files(self, monkeypatch, mock_db_session):
        from app.repositories import agent as agent_repo

        stored = StateBackend()
        stored.write("/out/report.csv", "a,b")
        monkeypatch.setattr(
            workspace_repo,
            "list_for_reader",
            AsyncMock(return_value=[_row(files=dict(stored.files))]),
        )
        monkeypatch.setattr(agent_repo, "get_many", AsyncMock(return_value={}))
        _no_conversations(monkeypatch)

        listing = await SandboxWorkspaceService(mock_db_session).flat_files(_ctx())

        assert all(not entry.get("is_dir") for _overview, entry in listing.files)

    async def test_a_partial_answer_says_it_is_partial(self, monkeypatch, mock_db_session):
        """Reading a container-backed workspace is a round trip to its host, so the
        bound is real - and a list that quietly stopped would read as "that is all
        the files there are"."""
        from app.repositories import agent as agent_repo

        monkeypatch.setattr(
            workspace_repo,
            "list_for_reader",
            AsyncMock(return_value=[_row(files={}) for _ in range(3)]),
        )
        monkeypatch.setattr(agent_repo, "get_many", AsyncMock(return_value={}))
        _no_conversations(monkeypatch)

        listing = await SandboxWorkspaceService(mock_db_session).flat_files(_ctx(), limit=2)

        assert listing.truncated is True
        assert listing.workspaces_read == 2

    async def test_one_unreadable_workspace_does_not_empty_the_list(
        self, monkeypatch, mock_db_session
    ):
        from app.repositories import agent as agent_repo

        stored = StateBackend()
        stored.write("/report.csv", "a")
        rows = [_row(files=dict(stored.files)), _row(backend="service", connection_id=uuid4())]
        monkeypatch.setattr(workspace_repo, "list_for_reader", AsyncMock(return_value=rows))
        monkeypatch.setattr(agent_repo, "get_many", AsyncMock(return_value={}))
        _no_conversations(monkeypatch)
        service = SandboxWorkspaceService(mock_db_session)
        service.connections = MagicMock(
            resolve=AsyncMock(side_effect=RuntimeError("the host is down"))
        )

        listing = await service.flat_files(_ctx())

        assert [str(entry.get("path")) for _overview, entry in listing.files] == ["/report.csv"]
        assert listing.unreadable == 1
        assert listing.workspaces_read == 1

    async def test_each_file_names_the_workspace_it_came_from(self, monkeypatch, mock_db_session):
        """`/report.csv` exists in several workspaces, so a path on its own is
        ambiguous - and who can see it is the whole point of the column."""
        from app.repositories import agent as agent_repo

        stored = StateBackend()
        stored.write("/report.csv", "a")
        row = _row(files=dict(stored.files), scope="agent")
        agent = MagicMock(id=row.agent_id)
        agent.name = "Analyst"
        monkeypatch.setattr(workspace_repo, "list_for_reader", AsyncMock(return_value=[row]))
        monkeypatch.setattr(agent_repo, "get_many", AsyncMock(return_value={row.agent_id: agent}))
        _no_conversations(monkeypatch)

        listing = await SandboxWorkspaceService(mock_db_session).flat_files(_ctx())

        [(overview, _entry)] = listing.files
        assert overview.agent_name == "Analyst"
        assert overview.access_label == "Everybody who talks to this agent"


class TestWhatReadingAHostCosts:
    """The resources a read acquires, and that it gives them back.

    Neither of these is visible from the answer a caller gets, which is why they
    went unnoticed: the archive fakes were instant and had no client to leak, so
    every one of these paths was covered and neither defect was reachable by a
    test. Both are asserted directly here rather than inferred.
    """

    @staticmethod
    def _archive_recording(monkeypatch, *, ls_fails: bool = False) -> list:
        from pydantic_ai_backends import remote as remote_module

        made: list = []

        class _Archive(_ClosesItsClient):
            def __init__(self, url, token=""):
                made.append(self)

            def ls(self, session_id):
                if ls_fails:
                    raise RuntimeError("This service keeps no workspaces on disk.")
                return [{"path": "/run.py", "size": 8, "is_dir": False}]

            def read(self, session_id, path):
                return "print(1)"

        monkeypatch.setattr(remote_module, "WorkspaceArchive", _Archive, raising=False)
        return made

    async def test_a_listing_closes_the_client_it_opened(self, monkeypatch, mock_db_session):
        """`WorkspaceArchive` owns an `httpx.Client`, and nothing used to release
        it - so a connection pool was abandoned on every read."""
        made = self._archive_recording(monkeypatch)
        _serve(monkeypatch, _resolved())
        row = _row(backend="service", session_id="dc-1", connection_id=uuid4())
        monkeypatch.setattr(workspace_repo, "list_for_conversation", AsyncMock(return_value=[row]))

        await SandboxWorkspaceService(mock_db_session).listing(_ctx(), conversation_id=uuid4())

        assert [archive.closed for archive in made] == [True]

    async def test_a_host_that_raises_still_has_its_client_closed(
        self, monkeypatch, mock_db_session
    ):
        """The failing path is the one that matters: a service keeping nothing on
        disk is the commonest answer here, so it is the commonest leak."""
        made = self._archive_recording(monkeypatch, ls_fails=True)
        _serve(monkeypatch, _resolved())
        row = _row(backend="service", session_id="dc-1", connection_id=uuid4())
        monkeypatch.setattr(workspace_repo, "list_for_conversation", AsyncMock(return_value=[row]))

        found = await SandboxWorkspaceService(mock_db_session).listing(
            _ctx(), conversation_id=uuid4()
        )

        assert found is not None
        assert found[1].unreadable_reason is not None
        assert [archive.closed for archive in made] == [True]

    async def test_a_read_closes_the_client_it_opened(self, monkeypatch, mock_db_session):
        made = self._archive_recording(monkeypatch)
        _serve(monkeypatch, _resolved())
        row = _row(backend="service", session_id="dc-1", connection_id=uuid4())
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))
        monkeypatch.setattr(workspace_repo, "list_for_reader", AsyncMock(return_value=[row]))

        await SandboxWorkspaceService(mock_db_session).read_file_of(_ctx(), row.id, path="/run.py")

        assert made
        assert all(archive.closed for archive in made)

    async def test_one_host_is_resolved_once_however_many_workspaces_it_holds(
        self, monkeypatch, mock_db_session
    ):
        """`resolve` is a query plus a vault unwrap, and this asked it per row - so
        a reader with twenty workspaces on one host paid twenty of each to read one
        page."""
        from app.repositories import agent as agent_repo

        self._archive_recording(monkeypatch)
        connection = uuid4()
        resolves = 0

        async def _resolve(self, ctx, connection_id):
            nonlocal resolves
            resolves += 1
            return _resolved()

        monkeypatch.setattr(SandboxConnectionService, "resolve", _resolve)
        rows = [
            _row(backend="service", session_id=f"dc-{n}", connection_id=connection)
            for n in range(4)
        ]
        monkeypatch.setattr(workspace_repo, "list_for_reader", AsyncMock(return_value=rows))
        monkeypatch.setattr(agent_repo, "get_many", AsyncMock(return_value={}))
        _no_conversations(monkeypatch)

        listing = await SandboxWorkspaceService(mock_db_session).flat_files(_ctx())

        assert listing.workspaces_read == 4
        assert resolves == 1

    async def test_two_hosts_are_resolved_separately(self, monkeypatch, mock_db_session):
        """The cache is keyed on the connection, so a second host is a second
        answer rather than the first one reused."""
        from app.repositories import agent as agent_repo

        self._archive_recording(monkeypatch)
        seen: list = []

        async def _resolve(self, ctx, connection_id):
            seen.append(connection_id)
            return _resolved()

        monkeypatch.setattr(SandboxConnectionService, "resolve", _resolve)
        first, second = uuid4(), uuid4()
        rows = [
            _row(backend="service", session_id="dc-1", connection_id=first),
            _row(backend="service", session_id="dc-2", connection_id=second),
        ]
        monkeypatch.setattr(workspace_repo, "list_for_reader", AsyncMock(return_value=rows))
        monkeypatch.setattr(agent_repo, "get_many", AsyncMock(return_value={}))
        _no_conversations(monkeypatch)

        await SandboxWorkspaceService(mock_db_session).flat_files(_ctx())

        assert sorted(map(str, seen)) == sorted(map(str, [first, second]))


class TestContainerBackedWorkspaces:
    """The paths that talk to something outside this process."""

    async def test_a_docker_workspace_labels_its_tenant_and_reattaches(
        self, monkeypatch, mock_db_session
    ):
        """`tenant` is capacity accounting, and `reuse` is what makes a
        conversation's workspace the same one next turn rather than a 409."""
        from pydantic_ai_backends import remote as remote_module

        seen: dict[str, object] = {}

        class _Sandbox:
            def __init__(self, url, **kwargs):
                seen.update(kwargs, url=url)

        monkeypatch.setattr(remote_module, "RemoteSandbox", _Sandbox)
        resolved = _resolved()
        _serve(monkeypatch, resolved)
        row = _row(backend="service")
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        created = AsyncMock(return_value=row)
        monkeypatch.setattr(workspace_repo, "create", created)
        identity = _identity()

        workspace = await SandboxWorkspaceService(mock_db_session).open(
            _spec(backend="service", runtime="python"), ctx=_ctx(), identity=identity
        )

        assert workspace is not None
        assert workspace.kind == "service"
        assert seen["url"] == "http://sandboxd:8080"
        assert seen["token"] == "service-token"
        assert seen["tenant"] == str(identity.organization_id)
        assert seen["reuse"] is True
        assert seen["runtime"] == "python"
        # The service is told which session belongs to this row, so deleting the
        # conversation can purge the sandbox rather than wait for a TTL. The
        # connection is recorded for the same reason: nothing later has the spec.
        assert created.await_args.kwargs["session_id"] == workspace.scope_key
        assert created.await_args.kwargs["connection_id"] == resolved.row.id

    async def test_the_connections_runtime_is_used_when_the_spec_names_none(
        self, monkeypatch, mock_db_session
    ):
        """Three levels, each answering a different question: what this agent
        needs, what this host prefers, and what exists at all."""
        from pydantic_ai_backends import remote as remote_module

        seen: dict[str, object] = {}
        monkeypatch.setattr(
            remote_module, "RemoteSandbox", lambda url, **kwargs: seen.update(kwargs) or object()
        )
        _serve(monkeypatch, _resolved(default_runtime="data-science"))
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        monkeypatch.setattr(
            workspace_repo, "create", AsyncMock(return_value=_row(backend="service"))
        )

        await SandboxWorkspaceService(mock_db_session).open(
            _spec(backend="service"), ctx=_ctx(), identity=_identity()
        )

        assert seen["runtime"] == "data-science"

    async def test_a_daytona_connection_uses_the_organizations_own_key(
        self, monkeypatch, mock_db_session
    ):
        """Daytona bills an account the *organization* owns, so the key comes
        from that organization's vault by way of its connection. The SDK's own
        `DAYTONA_API_KEY` fallback would put every tenant's sandboxes on
        whichever account the deployment happened to configure."""
        import pydantic_ai_backends as backends_module

        seen: dict[str, object] = {}

        class _Sandbox:
            def __init__(self, api_key=None, sandbox_id=None):
                seen.update(api_key=api_key, sandbox_id=sandbox_id)

        monkeypatch.setattr(backends_module, "DaytonaSandbox", _Sandbox, raising=False)
        _serve(monkeypatch, _resolved(kind="daytona", base_url=None, token="dtn-live-key"))
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        monkeypatch.setattr(
            workspace_repo, "create", AsyncMock(return_value=_row(backend="service"))
        )

        workspace = await SandboxWorkspaceService(mock_db_session).open(
            _spec(backend="service"), ctx=_ctx(), identity=_identity()
        )

        assert workspace is not None
        assert seen["api_key"] == "dtn-live-key"
        assert seen["sandbox_id"] == workspace.scope_key

    async def test_the_spec_may_name_a_connection_other_than_the_default(
        self, monkeypatch, mock_db_session
    ):
        """Two hosts is the whole reason connections are rows. An agent that
        names one has to reach that one, not whichever is marked default."""
        from pydantic_ai_backends import remote as remote_module

        monkeypatch.setattr(remote_module, "RemoteSandbox", lambda url, **kwargs: object())
        asked: list[UUID | None] = []

        async def _resolve(self, ctx, connection_id):
            asked.append(connection_id)
            return _resolved()

        monkeypatch.setattr(SandboxConnectionService, "resolve", _resolve)
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        monkeypatch.setattr(
            workspace_repo, "create", AsyncMock(return_value=_row(backend="service"))
        )
        named = uuid4()

        await SandboxWorkspaceService(mock_db_session).open(
            _spec(backend="service", connection_id=str(named)), ctx=_ctx(), identity=_identity()
        )

        assert asked == [named]

    async def test_a_run_scoped_sandbox_is_released_when_the_run_ends(
        self, monkeypatch, mock_db_session
    ):
        from pydantic_ai_backends import remote as remote_module

        stopped: dict[str, object] = {}

        class _Sandbox:
            def __init__(self, url, **kwargs):
                pass

            def stop(self, purge=False):
                stopped["purge"] = purge

        monkeypatch.setattr(remote_module, "RemoteSandbox", _Sandbox)
        _serve(monkeypatch, _resolved())
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(
            _spec(backend="service", session_scope="run"), ctx=_ctx(), identity=_identity()
        )
        await service.close(workspace)

        assert stopped == {"purge": True}

    async def test_a_conversation_scoped_sandbox_outlives_the_run(
        self, monkeypatch, mock_db_session
    ):
        """The next turn is meant to find the files this one wrote."""
        from pydantic_ai_backends import remote as remote_module

        stopped: list[bool] = []

        class _Sandbox:
            def __init__(self, url, **kwargs):
                pass

            def stop(self, purge=False):
                stopped.append(purge)

        monkeypatch.setattr(remote_module, "RemoteSandbox", _Sandbox)
        _serve(monkeypatch, _resolved())
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        monkeypatch.setattr(
            workspace_repo, "create", AsyncMock(return_value=_row(backend="service"))
        )
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(_spec(backend="service"), ctx=_ctx(), identity=_identity())
        await service.close(workspace)

        assert stopped == []

    async def test_a_backend_that_cannot_be_stopped_is_left_alone(
        self, monkeypatch, mock_db_session
    ):
        """A Daytona sandbox exposes no `stop`, and `close` must not care."""
        import pydantic_ai_backends as backends_module

        class _Sandbox:
            def __init__(self, api_key=None, sandbox_id=None):
                pass

        monkeypatch.setattr(backends_module, "DaytonaSandbox", _Sandbox, raising=False)
        _serve(monkeypatch, _resolved(kind="daytona", base_url=None))
        service = SandboxWorkspaceService(mock_db_session)

        workspace = await service.open(
            _spec(backend="service", session_scope="run"), ctx=_ctx(), identity=_identity()
        )
        await service.close(workspace)


class TestDeletingAConversation:
    async def test_every_workspace_of_the_conversation_goes(self, monkeypatch, mock_db_session):
        rows = [_row(), _row()]
        monkeypatch.setattr(workspace_repo, "list_for_conversation", AsyncMock(return_value=rows))
        deleted = AsyncMock()
        monkeypatch.setattr(workspace_repo, "delete", deleted)

        count = await SandboxWorkspaceService(mock_db_session).purge_for_conversation(
            _ctx(), conversation_id=uuid4()
        )

        assert count == 2
        assert deleted.await_count == 2

    async def test_a_container_workspace_is_purged_on_the_service_too(
        self, monkeypatch, mock_db_session
    ):
        """The row would cascade away; the container would sit on the host."""
        from pydantic_ai_backends import remote as remote_module

        purged: list[str] = []

        class _Sandbox:
            def __init__(self, url, **kwargs):
                purged.append(kwargs["session_id"])

            def stop(self, purge=False):
                pass

        monkeypatch.setattr(remote_module, "RemoteSandbox", _Sandbox)
        _serve(monkeypatch, _resolved())
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(
                return_value=[_row(backend="service", session_id="dc-1", connection_id=uuid4())]
            ),
        )
        monkeypatch.setattr(workspace_repo, "delete", AsyncMock())

        await SandboxWorkspaceService(mock_db_session).purge_for_conversation(
            _ctx(), conversation_id=uuid4()
        )

        assert purged == ["dc-1"]

    async def test_a_service_that_is_down_does_not_stop_the_deletion(
        self, monkeypatch, mock_db_session
    ):
        """The workspace TTL is the net under exactly this."""
        from pydantic_ai_backends import remote as remote_module

        class _Sandbox:
            def __init__(self, url, **kwargs):
                raise RuntimeError("connection refused")

        monkeypatch.setattr(remote_module, "RemoteSandbox", _Sandbox)
        _serve(monkeypatch, _resolved())
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(
                return_value=[_row(backend="service", session_id="dc-1", connection_id=uuid4())]
            ),
        )
        deleted = AsyncMock()
        monkeypatch.setattr(workspace_repo, "delete", deleted)

        count = await SandboxWorkspaceService(mock_db_session).purge_for_conversation(
            _ctx(), conversation_id=uuid4()
        )

        assert count == 1
        deleted.assert_awaited_once()

    async def test_a_connection_deleted_since_does_not_stop_the_deletion(
        self, monkeypatch, mock_db_session
    ):
        """`SET NULL` makes this reachable: the host was forgotten, the row that
        records what an agent did on it was not. Deleting the chat still works."""
        _serve(monkeypatch, BadRequestError(message="that connection no longer exists"))
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(
                return_value=[_row(backend="service", session_id="dc-1", connection_id=uuid4())]
            ),
        )
        deleted = AsyncMock()
        monkeypatch.setattr(workspace_repo, "delete", deleted)

        count = await SandboxWorkspaceService(mock_db_session).purge_for_conversation(
            _ctx(), conversation_id=uuid4()
        )

        assert count == 1
        deleted.assert_awaited_once()

    async def test_a_daytona_workspace_is_dropped_without_a_sandboxd_call(
        self, monkeypatch, mock_db_session
    ):
        """Its sandbox lives on the organization's own Daytona account, which
        keeps no session of ours to purge - so the row goes and nothing is
        called. Reaching for `RemoteSandbox` here would send a Daytona key to a
        `sandboxd` that does not exist."""
        _serve(monkeypatch, _resolved(kind="daytona", base_url=None))
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(
                return_value=[_row(backend="service", session_id="dt-1", connection_id=uuid4())]
            ),
        )
        deleted = AsyncMock()
        monkeypatch.setattr(workspace_repo, "delete", deleted)

        count = await SandboxWorkspaceService(mock_db_session).purge_for_conversation(
            _ctx(), conversation_id=uuid4()
        )

        assert count == 1
        deleted.assert_awaited_once()

    async def test_a_state_workspace_needs_no_service_call(self, monkeypatch, mock_db_session):
        monkeypatch.setattr(
            workspace_repo, "list_for_conversation", AsyncMock(return_value=[_row()])
        )
        monkeypatch.setattr(workspace_repo, "delete", AsyncMock())

        assert (
            await SandboxWorkspaceService(mock_db_session).purge_for_conversation(
                _ctx(), conversation_id=uuid4()
            )
            == 1
        )

    async def test_a_workspace_whose_host_was_forgotten_is_still_deleted(
        self, monkeypatch, mock_db_session
    ):
        """No `connection_id` left means nothing to ask, not a failure."""
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(
                return_value=[_row(backend="service", session_id="dc-1", connection_id=None)]
            ),
        )
        monkeypatch.setattr(workspace_repo, "delete", AsyncMock())

        assert (
            await SandboxWorkspaceService(mock_db_session).purge_for_conversation(
                _ctx(), conversation_id=uuid4()
            )
            == 1
        )


class TestShowingTheFilesToAPerson:
    """Listing and reading, which the conversation routes proxy.

    No sandbox is started for a container-backed workspace: the files are read
    off the volume the service keeps, which is what makes a conversation from
    last week list its files at all after its session was reaped.
    """

    async def test_a_conversation_with_no_workspace_lists_nothing(
        self, monkeypatch, mock_db_session
    ):
        monkeypatch.setattr(workspace_repo, "list_for_conversation", AsyncMock(return_value=[]))

        found = await SandboxWorkspaceService(mock_db_session).listing(
            _ctx(), conversation_id=uuid4()
        )

        assert found is None

    async def test_a_state_workspace_lists_what_it_holds(self, monkeypatch, mock_db_session):
        stored = StateBackend()
        stored.write("/uploads/report.csv", "month,total")
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(return_value=[_row(files=dict(stored.files))]),
        )

        found = await SandboxWorkspaceService(mock_db_session).listing(
            _ctx(), conversation_id=uuid4()
        )

        assert found is not None
        _, contents = found
        assert [entry["path"] for entry in contents.entries] == ["/uploads/report.csv"]
        assert contents.unreadable_reason is None

    async def test_a_state_file_is_read_back(self, monkeypatch, mock_db_session):
        stored = StateBackend()
        stored.write("/uploads/report.csv", "month,total")
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(return_value=[_row(files=dict(stored.files))]),
        )

        text = await SandboxWorkspaceService(mock_db_session).read_text(
            _ctx(), conversation_id=uuid4(), path="/uploads/report.csv"
        )

        assert text is not None
        assert "month,total" in text

    async def test_reading_by_id_a_path_a_host_did_not_list_is_nothing(
        self, monkeypatch, mock_db_session
    ):
        """The text path answers the same way the byte path does, from the listing -
        and only for a workspace kept on a host, because a stored one has `exists`."""
        from pydantic_ai_backends import remote as remote_module

        class _Archive(_ClosesItsClient):
            def __init__(self, url, token=""):
                pass

            def ls(self, session_id):
                return [{"path": "/run.py", "size": 8, "is_dir": False}]

            def read(self, session_id, path):
                raise AssertionError("the listing should have answered first")

        monkeypatch.setattr(remote_module, "WorkspaceArchive", _Archive, raising=False)
        _serve(monkeypatch, _resolved())
        row = _row(backend="service", session_id="dc-1", connection_id=uuid4())
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))

        assert (
            await SandboxWorkspaceService(mock_db_session).read_file_of(
                _ctx(), row.id, path="/typo.py"
            )
            is None
        )

    async def test_a_path_that_is_not_there_reads_as_nothing(self, monkeypatch, mock_db_session):
        monkeypatch.setattr(
            workspace_repo, "list_for_conversation", AsyncMock(return_value=[_row(files={})])
        )

        assert (
            await SandboxWorkspaceService(mock_db_session).read_text(
                _ctx(), conversation_id=uuid4(), path="/nope.txt"
            )
            is None
        )

    async def test_reading_from_a_conversation_with_no_workspace_is_nothing(
        self, monkeypatch, mock_db_session
    ):
        monkeypatch.setattr(workspace_repo, "list_for_conversation", AsyncMock(return_value=[]))

        assert (
            await SandboxWorkspaceService(mock_db_session).read_text(
                _ctx(), conversation_id=uuid4(), path="/a.txt"
            )
            is None
        )

    async def test_a_container_workspace_is_read_off_the_host_volume(
        self, monkeypatch, mock_db_session
    ):
        from pydantic_ai_backends import remote as remote_module

        class _Archive(_ClosesItsClient):
            def __init__(self, url, token=""):
                pass

            def ls(self, session_id):
                return [{"path": "/workspace/run.py", "size": 12, "is_dir": False}]

            def read(self, session_id, path):
                return "print(1)"

        monkeypatch.setattr(remote_module, "WorkspaceArchive", _Archive, raising=False)
        _serve(monkeypatch, _resolved())
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(
                return_value=[_row(backend="service", session_id="dc-1", connection_id=uuid4())]
            ),
        )
        service = SandboxWorkspaceService(mock_db_session)

        found = await service.listing(_ctx(), conversation_id=uuid4())
        text = await service.read_text(_ctx(), conversation_id=uuid4(), path="/workspace/run.py")

        assert found is not None
        assert found[1].entries[0]["path"] == "/workspace/run.py"
        assert text == "print(1)"

    async def test_a_host_that_cannot_be_read_says_so_instead_of_looking_empty(
        self, monkeypatch, mock_db_session
    ):
        """An empty folder is what a user believes, and a 500 said nothing at all -
        the panel showed "an unexpected error occurred" beside "nothing yet", which
        is two wrong answers at once. The commonest cause is not even a fault: a
        service with no `workspace_root` keeps nothing on disk, so its files exist
        only while a sandbox runs."""
        from pydantic_ai_backends import remote as remote_module

        class _Archive(_ClosesItsClient):
            def __init__(self, url, token=""):
                pass

            def ls(self, session_id):
                raise RuntimeError("This service keeps no workspaces on disk.")

        monkeypatch.setattr(remote_module, "WorkspaceArchive", _Archive, raising=False)
        _serve(monkeypatch, _resolved())
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(
                return_value=[_row(backend="service", session_id="dc-1", connection_id=uuid4())]
            ),
        )

        found = await SandboxWorkspaceService(mock_db_session).listing(
            _ctx(), conversation_id=uuid4()
        )

        assert found is not None
        _, contents = found
        assert contents.entries == []
        # The service's own detail is kept: it names the setting, which is the
        # difference between an operator fixing this and filing a bug against us.
        assert "keeps no workspaces on disk" in (contents.unreadable_reason or "")

    async def test_a_file_on_a_host_that_cannot_be_read_is_refused_not_reported_missing(
        self, monkeypatch, mock_db_session
    ):
        """A 404 would say the file is not there. It is; this host cannot serve it."""
        from pydantic_ai_backends import remote as remote_module

        class _Archive(_ClosesItsClient):
            def __init__(self, url, token=""):
                pass

            def ls(self, session_id):
                return []

            def read(self, session_id, path):
                raise RuntimeError("This service keeps no workspaces on disk.")

        monkeypatch.setattr(remote_module, "WorkspaceArchive", _Archive, raising=False)
        _serve(monkeypatch, _resolved())
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(
                return_value=[_row(backend="service", session_id="dc-1", connection_id=uuid4())]
            ),
        )

        with pytest.raises(BadRequestError) as refused:
            await SandboxWorkspaceService(mock_db_session).read_text(
                _ctx(), conversation_id=uuid4(), path="/workspace/run.py"
            )

        assert "could not be read" in refused.value.message

    async def test_a_daytona_workspace_keeps_no_volume_of_ours_to_list(
        self, monkeypatch, mock_db_session
    ):
        """Its files live on their account, so "none here" is the true answer -
        and it must not be confused with the service being misconfigured."""
        _serve(monkeypatch, _resolved(kind="daytona", base_url=None))
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(
                return_value=[_row(backend="service", session_id="dt-1", connection_id=uuid4())]
            ),
        )
        service = SandboxWorkspaceService(mock_db_session)

        found = await service.listing(_ctx(), conversation_id=uuid4())

        assert found is not None
        assert found[1].entries == []
        assert found[1].unreadable_reason is None
        assert await service.read_text(_ctx(), conversation_id=uuid4(), path="/a.txt") is None

    async def test_a_workspace_whose_host_was_forgotten_lists_nothing(
        self, monkeypatch, mock_db_session
    ):
        """The row survives a deleted connection on purpose - it records what an
        agent did - and browsing it answers "no files" rather than failing."""
        monkeypatch.setattr(
            workspace_repo,
            "list_for_conversation",
            AsyncMock(
                return_value=[_row(backend="service", session_id="dc-1", connection_id=None)]
            ),
        )
        service = SandboxWorkspaceService(mock_db_session)

        found = await service.listing(_ctx(), conversation_id=uuid4())

        assert found is not None
        assert found[1].entries == []
        assert found[1].unreadable_reason is None
        assert await service.read_text(_ctx(), conversation_id=uuid4(), path="/a.txt") is None


class TestBrowsingEveryWorkspace:
    """The operator view, which addresses a workspace by its own id.

    Not through a conversation, because two of the four scopes have none to be
    addressed through: a `run` workspace never had one and an `agent` one belongs
    to every conversation the agent ever answered.
    """

    async def test_a_listing_names_the_agent_rather_than_its_id(self, monkeypatch, mock_db_session):
        """A table of hex strings would make the client fetch the agents to render
        it, which is a round trip per page to say something we already know."""
        from app.repositories import agent as agent_repo

        row = _row()
        agent = MagicMock(id=row.agent_id)
        agent.name = "Analyst"
        monkeypatch.setattr(workspace_repo, "list_for_reader", AsyncMock(return_value=[row]))
        monkeypatch.setattr(agent_repo, "get_many", AsyncMock(return_value={row.agent_id: agent}))
        _no_conversations(monkeypatch)

        [overview] = await SandboxWorkspaceService(mock_db_session).visible_to(_ctx())

        assert overview.row is row
        assert overview.agent_name == "Analyst"

    async def test_a_workspace_of_a_deleted_agent_still_lists(self, monkeypatch, mock_db_session):
        """`SET NULL` is not used on `agent_id` - it cascades - but a row can
        outlive the lookup by a moment, and a listing that raised over it would
        hide every other workspace in the organization."""
        from app.repositories import agent as agent_repo

        monkeypatch.setattr(workspace_repo, "list_for_reader", AsyncMock(return_value=[_row()]))
        monkeypatch.setattr(agent_repo, "get_many", AsyncMock(return_value={}))
        _no_conversations(monkeypatch)

        [overview] = await SandboxWorkspaceService(mock_db_session).visible_to(_ctx())

        assert overview.agent_name == "a deleted agent"

    async def test_an_organization_with_no_workspaces_asks_for_no_agents(
        self, monkeypatch, mock_db_session
    ):
        from app.repositories import agent as agent_repo

        monkeypatch.setattr(workspace_repo, "list_for_reader", AsyncMock(return_value=[]))
        looked_up = AsyncMock()
        monkeypatch.setattr(agent_repo, "get_many", looked_up)

        assert await SandboxWorkspaceService(mock_db_session).visible_to(_ctx()) == []
        looked_up.assert_not_called()

    async def test_the_conversation_behind_a_workspace_is_named(self, monkeypatch, mock_db_session):
        """A table of conversation ids is a table nobody can read, and "which chat
        are these files from" is the first question asked of one."""
        from app.repositories import agent as agent_repo
        from app.repositories import conversation as conversation_repo

        row = _row(scope="conversation", conversation_id=uuid4())
        monkeypatch.setattr(workspace_repo, "list_for_reader", AsyncMock(return_value=[row]))
        monkeypatch.setattr(agent_repo, "get_many", AsyncMock(return_value={}))
        monkeypatch.setattr(
            conversation_repo,
            "titles_for",
            AsyncMock(return_value={row.conversation_id: "Refund policy"}),
        )
        monkeypatch.setattr(conversation_repo, "count_by_agent", AsyncMock(return_value={}))

        [overview] = await SandboxWorkspaceService(mock_db_session).visible_to(_ctx())

        assert overview.conversation_title == "Refund policy"
        assert overview.conversations == 1

    async def test_a_shared_workspace_says_how_many_chats_reach_it(
        self, monkeypatch, mock_db_session
    ):
        """Under `agent` scope one workspace is shared by everybody who talks to
        that agent, and the number is the difference between "my files" and
        "everybody's"."""
        from app.repositories import agent as agent_repo
        from app.repositories import conversation as conversation_repo

        row = _row(scope="agent", conversation_id=None)
        monkeypatch.setattr(workspace_repo, "list_for_reader", AsyncMock(return_value=[row]))
        monkeypatch.setattr(agent_repo, "get_many", AsyncMock(return_value={}))
        monkeypatch.setattr(conversation_repo, "titles_for", AsyncMock(return_value={}))
        counted = AsyncMock(return_value={row.agent_id: 12})
        monkeypatch.setattr(conversation_repo, "count_by_agent", counted)

        [overview] = await SandboxWorkspaceService(mock_db_session).visible_to(_ctx())

        assert overview.conversations == 12
        assert overview.access_label == "Everybody who talks to this agent"

    async def test_a_run_scoped_workspace_counts_nobody(self, monkeypatch, mock_db_session):
        """It is deleted when the run ends, so there is no chat to reach it - and
        counting the agent's conversations would claim twelve people can see files
        that no longer exist."""
        from app.repositories import agent as agent_repo
        from app.repositories import conversation as conversation_repo

        monkeypatch.setattr(
            workspace_repo,
            "list_for_reader",
            AsyncMock(return_value=[_row(scope="run", conversation_id=None)]),
        )
        monkeypatch.setattr(agent_repo, "get_many", AsyncMock(return_value={}))
        counted = AsyncMock(return_value={})
        monkeypatch.setattr(conversation_repo, "titles_for", AsyncMock(return_value={}))
        monkeypatch.setattr(conversation_repo, "count_by_agent", counted)

        [overview] = await SandboxWorkspaceService(mock_db_session).visible_to(_ctx())

        assert overview.conversations == 0
        counted.assert_not_called()

    async def test_the_files_of_one_workspace_come_back_with_its_row(
        self, monkeypatch, mock_db_session
    ):
        stored = StateBackend()
        stored.write("/uploads/report.csv", "month,total")
        row = _row(files=dict(stored.files))
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))

        found, contents = await SandboxWorkspaceService(mock_db_session).files_of(_ctx(), row.id)

        assert found is row
        assert [entry["path"] for entry in contents.entries] == ["/uploads/report.csv"]

    async def test_another_organizations_workspace_reads_as_missing(
        self, monkeypatch, mock_db_session
    ):
        """Not "forbidden": a probeable id is how somebody maps which workspaces
        exist in the organizations they are not in."""
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=None))

        with pytest.raises(NotFoundError):
            await SandboxWorkspaceService(mock_db_session).files_of(_ctx(), uuid4())

    async def test_one_file_is_read_out_of_it(self, monkeypatch, mock_db_session):
        stored = StateBackend()
        stored.write("/uploads/report.csv", "month,total")
        row = _row(files=dict(stored.files))
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))

        text = await SandboxWorkspaceService(mock_db_session).read_file_of(
            _ctx(), row.id, path="/uploads/report.csv"
        )

        assert text is not None
        assert "month,total" in text

    async def test_a_path_that_is_not_in_it_reads_as_nothing(self, monkeypatch, mock_db_session):
        row = _row(files={})
        monkeypatch.setattr(workspace_repo, "get", AsyncMock(return_value=row))

        assert (
            await SandboxWorkspaceService(mock_db_session).read_file_of(
                _ctx(), row.id, path="/nope.txt"
            )
            is None
        )


class TestWhoseWorkspaceItIs:
    """A user seeing a file they never created should be able to find out why."""

    @pytest.mark.parametrize(
        ("scope", "expected"),
        [
            ("conversation", "This conversation"),
            ("user", "Your files for this agent"),
            ("agent", "Shared by everyone who uses this agent"),
            ("run", "This run only"),
        ],
    )
    def test_the_label_names_the_scope_in_words(self, scope: str, expected: str):
        from app.services.sandbox_workspace import owner_label

        assert owner_label(_row(scope=scope)) == expected

    @pytest.mark.parametrize(
        ("scope", "expected"),
        [
            ("conversation", "Whoever is in that conversation"),
            ("user", "One person, in this agent only"),
            ("agent", "Everybody who talks to this agent"),
            ("channel", "Everybody in that chat"),
            ("run", "Nobody - it is deleted when the run ends"),
        ],
    )
    def test_access_says_the_consequence_rather_than_the_mechanism(self, scope: str, expected: str):
        """`owner_label` addresses whoever is in the chat; this addresses somebody
        auditing a table of files, and "agent" does not tell them whether the file
        in front of them is one person's or the whole team's."""
        from app.services.sandbox_workspace import access_label

        assert access_label(_row(scope=scope)) == expected
