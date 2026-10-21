"""A project's container: one per project, every agent's in it, no one agent's.

What `tests/test_project_service.py` cannot show is below the service: the key a
project's container is opened under is the same whichever agent or run asks, a
run outside a project cannot reach one, the row it creates carries the project
and no agent, and a run in a project is given the container - and the project's
instructions - even when its agent keeps no workspace of its own.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.capabilities.sandbox._identity import (
    WorkspaceIdentity,
    WorkspaceScopeUnavailable,
    scope_key,
)
from app.agents.spec import AgentSpec
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_workspace import AgentWorkspace
from app.repositories import agent_workspace as workspace_repo
from app.services.agent_runner import _in_project
from app.services.sandbox_workspace import (
    SandboxWorkspaceService,
    WorkspaceContents,
    access_label,
    owner_label,
)

pytestmark = pytest.mark.anyio


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)


def _project(**overrides: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "id": uuid4(),
        "name": "Launch",
        "description": None,
        "instructions": "",
        "backend": "state",
        "sandbox_connection_id": None,
        "runtime": None,
    }
    return SimpleNamespace(**{**fields, **overrides})


def _row(**overrides: object) -> AgentWorkspace:
    row = AgentWorkspace(
        id=uuid4(),
        organization_id=uuid4(),
        agent_id=None,
        project_id=uuid4(),
        scope="project",
        scope_key="dp-cafe",
        backend="state",
        files=None,
        bytes_total=0,
        version=0,
    )
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


class TestOneContainerPerProject:
    def test_every_agent_and_run_in_a_project_opens_the_same_one(self) -> None:
        organization, project = uuid4(), uuid4()

        def key() -> str:
            identity = WorkspaceIdentity(
                organization_id=organization, agent_id=uuid4(), run_id=uuid4(), project_id=project
            )
            return scope_key(identity, "project", "state")

        assert key() == key()

    def test_a_run_outside_a_project_cannot_reach_one(self) -> None:
        identity = WorkspaceIdentity(organization_id=uuid4(), agent_id=uuid4(), run_id=uuid4())
        with pytest.raises(WorkspaceScopeUnavailable, match="not in a project"):
            scope_key(identity, "project", "state")

    def test_only_a_project_can_be_opened_without_an_agents_run(self) -> None:
        identity = WorkspaceIdentity(
            organization_id=uuid4(), agent_id=None, run_id=None, project_id=uuid4()
        )
        with pytest.raises(WorkspaceScopeUnavailable, match="without an agent's run"):
            scope_key(identity, "conversation", "state")

    def test_its_labels_say_who_shares_it(self) -> None:
        assert owner_label(_row()) == "This project, shared by every chat in it"
        assert access_label(_row()) == "Everybody the project is shared with"


class TestOpeningItOutsideARun:
    async def test_the_row_it_creates_is_the_projects_and_no_agents(
        self, monkeypatch: pytest.MonkeyPatch, mock_db_session: MagicMock
    ) -> None:
        project = _project()
        created = AsyncMock(return_value=_row(project_id=project.id))
        monkeypatch.setattr(workspace_repo, "get_by_key", AsyncMock(return_value=None))
        monkeypatch.setattr(workspace_repo, "create", created)

        opened = await SandboxWorkspaceService(mock_db_session).open_project(_ctx(), project)

        assert opened.kind == "state"
        assert created.await_args.kwargs["agent_id"] is None
        assert created.await_args.kwargs["project_id"] == project.id
        assert created.await_args.kwargs["scope"] == "project"

    async def test_an_empty_project_has_nothing_to_list_read_or_purge(
        self, monkeypatch: pytest.MonkeyPatch, mock_db_session: MagicMock
    ) -> None:
        monkeypatch.setattr(workspace_repo, "get_for_project", AsyncMock(return_value=None))
        monkeypatch.setattr(workspace_repo, "list_for_project", AsyncMock(return_value=[]))
        purged = AsyncMock()
        monkeypatch.setattr(SandboxWorkspaceService, "_purge_remote", purged)
        service = SandboxWorkspaceService(mock_db_session)

        assert await service.project_files(_ctx(), _project()) is None
        with pytest.raises(NotFoundError, match="holds no files"):
            await service.project_bytes(_ctx(), _project(), path="a.md")
        await service.purge_project(_ctx(), _project())
        purged.assert_not_awaited()

    async def test_a_held_project_is_listed_read_and_its_container_purged(
        self, monkeypatch: pytest.MonkeyPatch, mock_db_session: MagicMock
    ) -> None:
        row = _row(backend="service")
        contents = WorkspaceContents(entries=[])
        moved_from = _row(backend="service")
        monkeypatch.setattr(workspace_repo, "get_for_project", AsyncMock(return_value=row))
        # A project moved to another connection left a container on the first.
        monkeypatch.setattr(
            workspace_repo, "list_for_project", AsyncMock(return_value=[row, moved_from])
        )
        monkeypatch.setattr(SandboxWorkspaceService, "_tiled", AsyncMock(return_value=contents))
        monkeypatch.setattr(SandboxWorkspaceService, "_browsable", AsyncMock(return_value=contents))
        monkeypatch.setattr(SandboxWorkspaceService, "_bytes_from", AsyncMock(return_value=b"hi"))
        purged = AsyncMock()
        monkeypatch.setattr(SandboxWorkspaceService, "_purge_remote", purged)
        service = SandboxWorkspaceService(mock_db_session)

        assert await service.project_files(_ctx(), _project()) == (row, contents)
        assert await service.project_bytes(_ctx(), _project(), path="a.md") == b"hi"
        await service.purge_project(_ctx(), _project())
        assert [call.args[1] for call in purged.await_args_list] == [row, moved_from]

    async def test_a_stored_project_has_no_host_to_purge(
        self, monkeypatch: pytest.MonkeyPatch, mock_db_session: MagicMock
    ) -> None:
        monkeypatch.setattr(workspace_repo, "list_for_project", AsyncMock(return_value=[_row()]))
        purged = AsyncMock()
        monkeypatch.setattr(SandboxWorkspaceService, "_purge_remote", purged)

        await SandboxWorkspaceService(mock_db_session).purge_project(_ctx(), _project())

        purged.assert_not_awaited()


class TestARunInAProject:
    def test_an_agent_with_no_workspace_is_given_the_projects(self) -> None:
        project = _project(description="The Q3 launch.", instructions="  Cite sources.  ")
        spec = _in_project(AgentSpec(name="Writer", instructions="You write."), project)

        (binding,) = spec.capabilities
        assert binding.id == "sandbox"
        assert binding.config["backend"] == "state"
        assert spec.instructions.startswith("You write.\n\n## Project: Launch")
        assert "The Q3 launch." in spec.instructions
        # Several people talk in a project's chat: the agent is told how to tell them apart.
        assert "Each person's message starts with their name" in spec.instructions
        assert spec.instructions.endswith("### The project's instructions\n\nCite sources.")

    def test_a_coding_agent_is_left_out_where_the_project_has_no_shell(self) -> None:
        """A project the platform keeps files for has no container: a coding
        agent would fail every task there, so it is not run and the agent knows."""
        coder = AgentSpec(
            name="Coder",
            capabilities=[
                {"id": "coding_agent", "config": {"harness": "claude_code"}},
                {"id": "web_search"},
            ],
        )

        stored = _in_project(coder, _project())
        assert [binding.id for binding in stored.capabilities] == ["web_search", "sandbox"]
        assert "coding agent is not available in this project" in stored.instructions

        container = _in_project(coder, _project(backend="service"))
        assert [binding.id for binding in container.capabilities] == [
            "coding_agent",
            "web_search",
            "sandbox",
        ]
        assert "not available" not in container.instructions

    @pytest.mark.security
    def test_an_agents_own_workspace_is_replaced_and_its_approvals_kept(self) -> None:
        connection = uuid4()
        project = _project(backend="service", sandbox_connection_id=connection, runtime="python")
        spec = AgentSpec(
            name="Coder",
            capabilities=[
                {"id": "web_search"},
                {
                    "id": "sandbox",
                    "enabled": False,
                    "config": {"session_scope": "agent", "include_execute": False},
                    "approval": "required",
                },
            ],
        )

        ran = _in_project(spec, project)

        assert [binding.id for binding in ran.capabilities] == ["web_search", "sandbox"]
        sandbox = ran.capabilities[1]
        assert sandbox.approval == "required"
        assert sandbox.enabled is True
        assert sandbox.config["backend"] == "service"
        assert sandbox.config["connection_id"] == str(connection)
        assert sandbox.config["runtime"] == "python"
        assert sandbox.config["session_scope"] != "agent"
        assert "### The project's instructions" not in ran.instructions
