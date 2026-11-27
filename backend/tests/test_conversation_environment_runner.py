"""Only an ordinary private web-chat run receives the lazy owned GUI adapters."""

from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.capabilities.browser_use._toolset import RetainedBrowser
from app.db.models.agent_run import RunSurface
from tests.test_agent_runner import (
    _ctx,
)
from tests.test_agent_runner import (
    _in_no_group as _in_no_group,
)
from tests.test_agent_runner import (
    _no_connected_chat_bindings as _no_connected_chat_bindings,
)
from tests.test_agent_runner import (
    _no_current_cap as _no_current_cap,
)
from tests.test_agent_runner import (
    _nobody_the_account_describes as _nobody_the_account_describes,
)
from tests.test_agent_runner_voice import runner_with_mocks as runner_with_mocks

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def case(runner_with_mocks, monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_runner.conversation_share_repo.has_edit_share",
        AsyncMock(return_value=False),
    )
    return runner_with_mocks


@pytest.mark.parametrize("surface", [RunSurface.WEB, RunSurface.API, RunSurface.SLACK])
@pytest.mark.parametrize("keyed", [False, True])
async def test_runner_only_wires_private_person_owned_web_environments(case, surface, keyed):
    ctx = _ctx()
    if keyed:
        ctx = replace(ctx, api_key_id=uuid4())
    await case.service.prepare(ctx, uuid4(), surface=surface, conversation_id=uuid4())
    resources = case.build_agent.call_args.kwargs["resources"]
    expected = surface is RunSurface.WEB and not keyed
    assert ("conversation_browser" in resources) is expected
    assert ("conversation_desktop" in resources) is expected
    if expected:
        assert isinstance(resources["conversation_browser"], RetainedBrowser)
    case.opened.assert_awaited_once()


@pytest.mark.parametrize("option", ["test", "public_origin", "organization_mcp_only"])
async def test_auxiliary_and_public_web_runs_keep_their_existing_lifecycle(case, option):
    await case.service.prepare(
        _ctx(), uuid4(), surface=RunSurface.WEB, conversation_id=uuid4(), **{option: True}
    )
    resources = case.build_agent.call_args.kwargs["resources"]
    assert "conversation_browser" not in resources
    assert "conversation_desktop" not in resources


@pytest.mark.parametrize("verified", [False, True])
async def test_root_shared_scope_captures_original_executor_fingerprint_without_re_resolving(
    case, monkeypatch, verified
):
    from app.agents.spec import AgentSpec, CapabilityBindingSpec
    from app.core.exceptions import ConflictError
    from app.services.agent_registry import DELEGATION_CAPABILITY_ID
    from app.services.conversation_environment_delegates import NESTED_DESKTOP_AUTHORITY
    from app.services.sandbox_workspace import OpenWorkspace
    from tests.workspaces import document_workspace

    agent, previous, version = case.runnable.return_value
    current = AgentSpec(
        name=previous.name,
        model_profile_id=previous.model_profile_id,
        capabilities=[
            CapabilityBindingSpec(id="sandbox", config={"backend": "service"}),
            CapabilityBindingSpec(id=DELEGATION_CAPABILITY_ID, config={}),
        ],
    )
    case.runnable.return_value = agent, current, version
    opened = OpenWorkspace(
        workspace=document_workspace(),
        kind="service",
        scope="conversation",
        scope_key="actual-executor",
        row_id=uuid4(),
        connection_id=uuid4(),
        connection_fingerprint="original-connection" if verified else None,
    )
    case.opened.return_value = opened
    monkeypatch.setattr(case.service, "_workspace_shared", AsyncMock(return_value=False))
    monkeypatch.setattr(case.service, "_delegation_runtime", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.services.attachments.chat_file_repo.left_by_interrupted_turns",
        AsyncMock(return_value=[]),
    )
    resolve = AsyncMock()
    monkeypatch.setattr(case.service.workspaces.connections, "resolve", resolve)
    if not verified:
        with pytest.raises(ConflictError, match="verified connection identity"):
            await case.service.prepare(
                _ctx(), uuid4(), surface=RunSurface.WEB, conversation_id=uuid4()
            )
    else:
        await case.service.prepare(_ctx(), uuid4(), surface=RunSurface.WEB, conversation_id=uuid4())
        nested = case.build_agent.call_args.kwargs["resources"][NESTED_DESKTOP_AUTHORITY]
        assert nested.workspace.connection_fingerprint == "original-connection"
        assert nested.workspace.scope_key == opened.scope_key
    resolve.assert_not_awaited()


@pytest.mark.parametrize("lifetime", ["run", "conversation"])
async def test_project_mount_is_lazy_and_only_retained_desktop_gets_the_environment_directory(
    case, monkeypatch, lifetime
):
    from app.agents.spec import AgentSpec, CapabilityBindingSpec
    from app.services.conversation_environment_agent import AgentEnvironment
    from app.services.sandbox_workspace import OpenWorkspace
    from tests.workspaces import document_workspace

    agent, previous, version = case.runnable.return_value
    current = AgentSpec(
        name=previous.name,
        model_profile_id=previous.model_profile_id,
        capabilities=[
            CapabilityBindingSpec(
                id="sandbox", config={"backend": "service", "session_scope": "conversation"}
            ),
            CapabilityBindingSpec(
                id="computer_use", config={"desktop": "sandbox", "session_lifetime": lifetime}
            ),
        ],
    )
    case.runnable.return_value = agent, current, version
    opened = OpenWorkspace(
        workspace=document_workspace(),
        kind="service",
        scope="conversation",
        scope_key="actual-executor",
        row_id=uuid4(),
        connection_id=uuid4(),
        connection_fingerprint="captured-parent-A",
    )
    case.opened.return_value = opened
    monkeypatch.setattr(case.service, "_workspace_shared", AsyncMock(return_value=False))
    monkeypatch.setattr(
        "app.services.attachments.chat_file_repo.left_by_interrupted_turns",
        AsyncMock(return_value=[]),
    )
    acquire = AsyncMock()
    monkeypatch.setattr(AgentEnvironment, "acquire", acquire)
    prepared = await case.service.prepare(
        _ctx(), uuid4(), surface=RunSurface.WEB, conversation_id=uuid4()
    )
    selector = prepared.project_workspace
    assert selector is not None
    if lifetime == "conversation":
        assert selector.environment_project_directory is not None
        assert selector.finish_environment_project_directory is not None
        assert (
            selector.environment_project_directory.__self__.workspace.connection_fingerprint
            == "captured-parent-A"
        )
    else:
        assert selector.environment_project_directory is None
        assert selector.finish_environment_project_directory is None
    acquire.assert_not_awaited()
