"""Actual delegate filtering/building preserves child policy and shared driver authority."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.capabilities.computer_use._backends import ComputerFactoryDecorator
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun
from app.services import agent_runner as runners
from app.services.conversation_environment_delegates import (
    NESTED_DESKTOP_AUTHORITY,
    NestedDesktopAuthority,
    SharedDesktopWorkspace,
)
from tests.test_agent_runner import _db, _resolved_model

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("shared", [False, True])
async def test_actual_delegate_resource_filter_and_builder_use_child_specific_driver(
    monkeypatch, shared
):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    run = AgentRun(
        id=uuid4(),
        agent_id=uuid4(),
        agent_version_id=uuid4(),
        conversation_id=uuid4(),
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        status="running",
        surface="web",
    )
    scope = NestedDesktopAuthority(
        ctx,
        run.agent_id,
        run.agent_version_id,
        run.id,
        run.conversation_id,
        "agent",
        SharedDesktopWorkspace(uuid4(), "original-scope", "connection-hash"),
    )
    child = AgentSpec(
        name="Own desktop",
        capabilities=[
            CapabilityBindingSpec(
                id="computer_use", config={"desktop": "sandbox", "screen_width": 1024}
            )
        ],
    )
    parent_only = object()
    parent = {
        NESTED_DESKTOP_AUTHORITY: scope,
        "conversation_desktop": parent_only,
        "conversation_browser": parent_only,
    }
    service = runners.AgentRunnerService(_db())
    monkeypatch.setattr(service, "_bound_collections", AsyncMock(return_value={}))
    monkeypatch.setattr(service.skills, "resolve_for_agent", AsyncMock(return_value=[]))
    monkeypatch.setattr(service.context, "resolve_for_agent", AsyncMock(return_value=[]))
    resources = await service._delegate_resources(
        ctx,
        child,
        agent_id=None,
        shared=[CapabilityBindingSpec(id="sandbox")] if shared else [],
        parent_resources=parent,
        person_id=None,
    )
    filtered = resources[NESTED_DESKTOP_AUTHORITY]
    assert filtered.workspace == (scope.workspace if shared else None)
    assert "conversation_desktop" not in resources and "conversation_browser" not in resources
    assert parent[NESTED_DESKTOP_AUTHORITY].workspace is not None
    delegation = MagicMock(spec=runners._Delegation)
    delegation.ctx = ctx
    delegation.run = run
    delegation.render_variables = MagicMock(side_effect=lambda spec: spec)
    delegation.computer_resources = {}
    delegation.request_computer_access = None
    delegation.routine_check = None
    delegation.routine_action_check = None
    delegation.isolation = None
    delegation.answering_call = None
    delegation.user_id = str(ctx.user_id)
    delegation.user_name = None
    delegation.recorders = []
    delegation.budget = MagicMock()
    delegation.approvals = MagicMock()
    built = MagicMock()
    build = MagicMock(return_value=built)
    monkeypatch.setattr(runners, "build_agent", build)
    runners._delegate_builder(
        delegation,
        spec=child,
        model=_resolved_model(),
        agent_id=run.agent_id,
        resources=resources,
        secrets={},
        extra_toolsets=[],
    )()
    actual = build.call_args.kwargs["resources"]
    assert (isinstance(actual.get("conversation_desktop"), ComputerFactoryDecorator)) is shared
    assert "conversation_browser" not in actual
    assert actual.get("conversation_desktop") is not parent_only
    assert build.call_args.args[0].capabilities[0].config["screen_width"] == 1024
    if not shared:
        # A deeper share cannot resurrect access stripped by the immediate parent.
        assert filtered.delegated(shares_workspace=True).workspace is None
