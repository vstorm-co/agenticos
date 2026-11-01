"""Record attribution follows trusted execution, never a submitted cell."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.permissions import AuthContext
from app.services.virtual_tables import record_sources as sources
from app.services.workflow_execution import context

pytestmark = pytest.mark.anyio


@pytest.fixture
def auth():
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")


async def test_a_person_uses_their_name_and_id(monkeypatch, auth):
    person = AsyncMock(return_value=SimpleNamespace(full_name="Jordan", email="j@example.com"))
    monkeypatch.setattr(sources.user_repo, "get_by_id", person)
    source = await sources.source_for(AsyncMock(), auth)
    assert source.kind == "user" and source.id == auth.user_id and source.name == "Jordan"
    assert source.stored() == {
        "kind": "user",
        "id": str(auth.user_id),
        "name": "Jordan",
        "slug": None,
        "has_avatar": False,
        "avatar_color": None,
    }


async def test_missing_name_uses_email(monkeypatch, auth):
    monkeypatch.setattr(
        sources.user_repo,
        "get_by_id",
        AsyncMock(return_value=SimpleNamespace(full_name=None, email="j@example.com")),
    )
    assert (await sources.source_for(AsyncMock(), auth)).name == "j@example.com"


async def test_a_deleted_person_keeps_the_recorded_principal_id(monkeypatch, auth):
    monkeypatch.setattr(sources.user_repo, "get_by_id", AsyncMock(return_value=None))
    assert (await sources.source_for(AsyncMock(), auth)).name == "User"


async def test_a_public_api_key_is_an_api_source_not_its_owner(monkeypatch, auth):
    key_id = uuid4()
    monkeypatch.setattr(
        sources.api_key_repo,
        "get",
        AsyncMock(return_value=SimpleNamespace(id=key_id, internal=False, name="CRM sync")),
    )
    source = await sources.source_for(AsyncMock(), replace(auth, api_key_id=key_id))
    assert source.kind == "api" and source.id == key_id and source.name == "CRM sync"


async def test_a_key_deleted_during_the_request_stays_an_api_source(monkeypatch, auth):
    monkeypatch.setattr(sources.api_key_repo, "get", AsyncMock(return_value=None))
    assert (await sources.source_for(AsyncMock(), replace(auth, api_key_id=uuid4()))).kind == "api"


@pytest.mark.security
async def test_internal_mcp_keys_identify_the_agent_in_the_same_tenant(monkeypatch, auth):
    agent_id = uuid4()
    monkeypatch.setattr(
        sources.api_key_repo,
        "get",
        AsyncMock(return_value=SimpleNamespace(internal=True, source_agent_id=agent_id)),
    )
    lookup = AsyncMock(
        return_value=SimpleNamespace(
            name="Researcher", slug="researcher", has_avatar=True, avatar_color=3
        )
    )
    monkeypatch.setattr(sources.agent_repo, "get", lookup)
    db = AsyncMock()
    source = await sources.source_for(db, replace(auth, api_key_id=uuid4()))
    assert source.kind == "agent" and source.id == agent_id and source.name == "Researcher"
    lookup.assert_awaited_once_with(db, agent_id, organization_id=auth.organization_id)


async def test_inline_and_deleted_agents_keep_an_agent_identity(monkeypatch, auth):
    monkeypatch.setattr(sources.agent_repo, "get", AsyncMock(return_value=None))
    for agent_id in [None, uuid4()]:
        with sources.from_agent(agent_id):
            source = await sources.source_for(AsyncMock(), auth)
            assert source.kind == "agent" and source.id == agent_id


async def test_agent_context_resets_after_an_exception(monkeypatch, auth):
    monkeypatch.setattr(sources.user_repo, "get_by_id", AsyncMock(return_value=None))
    with pytest.raises(RuntimeError), sources.from_agent(uuid4()):
        raise RuntimeError("cancel the tool")
    assert (await sources.source_for(AsyncMock(), auth)).kind == "user"


async def test_a_workflow_step_is_not_attributed_to_its_publisher(monkeypatch, auth):
    workflow_id = uuid4()
    monkeypatch.setattr(
        sources.workflow_repo, "get", AsyncMock(return_value=SimpleNamespace(name="Lead intake"))
    )
    dispatch = context.DispatchContext(
        organization_id=auth.organization_id,
        workflow_run_id=uuid4(),
        node_run_id=uuid4(),
        node_instance_id=uuid4(),
        attempt_no=1,
        auth=auth,
        resumed_agent_run_id=None,
        workflow_id=workflow_id,
    )
    with context.dispatching_as(dispatch):
        source = await sources.source_for(AsyncMock(), auth)
    assert source.kind == "workflow" and source.id == workflow_id and source.name == "Lead intake"


async def test_an_unregistered_workflow_and_a_system_write_have_fallbacks(monkeypatch, auth):
    dispatch = context.DispatchContext(
        organization_id=auth.organization_id,
        workflow_run_id=uuid4(),
        node_run_id=uuid4(),
        node_instance_id=uuid4(),
        attempt_no=1,
        auth=auth,
        resumed_agent_run_id=None,
    )
    with context.dispatching_as(dispatch):
        assert (await sources.source_for(AsyncMock(), auth)).name == "Workflow"
    assert (await sources.source_for(AsyncMock(), replace(auth, user_id=None))).kind == "system"
