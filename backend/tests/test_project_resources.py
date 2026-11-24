"""Linking resources never widens their audience or copies their definition."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.artifact import Artifact
from app.db.models.project_resource import ProjectResource
from app.db.models.project_resource import ProjectResourceKind as Kind
from app.schemas.project_resource import ProjectResourceRef
from app.services import project_resources as module
from app.services.project_resources import ProjectResourceService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def setup(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    project_id = uuid4()
    service = ProjectResourceService(AsyncMock())
    monkeypatch.setattr(service.projects, "get", AsyncMock())
    repo = MagicMock()
    for method in (
        "list_resources",
        "get_resource",
        "member_ids",
        "add",
        "remove",
        "set_entrypoint",
    ):
        setattr(repo, method, AsyncMock())
    repo.list_resources.return_value = []
    monkeypatch.setattr(module, "resource_repo", repo)
    monkeypatch.setattr(module, "accessible_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr(module, "resolve_access", AsyncMock(return_value=True))
    return service, ctx, project_id, repo


async def test_visible_resources_search_and_apps_without_description(setup, monkeypatch):
    service, ctx, project_id, repo = setup
    agent = Agent(id=uuid4(), name="Research", description="Market analysis")
    app = Artifact(id=uuid4(), name="dashboard", title="Sales dashboard")
    hidden = Agent(id=uuid4(), name="Private", description="Secret")
    links = [(ProjectResource(is_entrypoint=False), row) for row in (agent, hidden)]
    repo.list_resources.side_effect = [links, [], [(ProjectResource(is_entrypoint=False), app)], []]
    monkeypatch.setattr(
        module, "accessible_ids", AsyncMock(side_effect=[{agent.id}, set(), {app.id}, set()])
    )
    result = await service.list_resources(ctx, project_id, search="research")
    assert [item.resource_id for item in result.items] == [agent.id]
    assert result.total == 1
    repo.list_resources.side_effect = [[], [], [(ProjectResource(is_entrypoint=False), app)], []]
    monkeypatch.setattr(module, "accessible_ids", AsyncMock(return_value={app.id}))
    result = await service.list_resources(ctx, project_id)
    assert result.items[0].description is None
    assert result.items[0].name == "Sales dashboard"


async def test_project_access_is_checked_before_any_member_query(setup):
    service, ctx, project_id, repo = setup
    service.projects.get.side_effect = NotFoundError(message="Project not found")
    with pytest.raises(NotFoundError):
        await service.member_ids(ctx, project_id, Kind.AGENT)
    repo.member_ids.assert_not_awaited()


async def test_member_ids_do_not_replace_the_registry_permission_filter(setup):
    service, ctx, project_id, repo = setup
    repo.member_ids.return_value = [uuid4()]
    assert await service.member_ids(ctx, project_id, Kind.AGENT) == repo.member_ids.return_value
    assert repo.member_ids.await_args.kwargs["organization_id"] == ctx.organization_id


@pytest.mark.parametrize("missing", [True, False])
async def test_add_validates_entire_batch_before_writing(setup, monkeypatch, missing):
    service, ctx, project_id, repo = setup
    agent = Agent(id=uuid4(), name="Visible")
    repo.get_resource.side_effect = [agent, None if missing else agent]
    monkeypatch.setattr(module, "resolve_access", AsyncMock(side_effect=[True, False]))
    refs = [ProjectResourceRef(kind=Kind.AGENT, resource_id=uuid4()) for _ in range(2)]
    with pytest.raises(NotFoundError):
        await service.add(ctx, project_id, refs)
    repo.add.assert_not_awaited()
    assert repo.get_resource.await_args.kwargs["organization_id"] == ctx.organization_id


async def test_add_and_remove_change_links_only(setup):
    service, ctx, project_id, repo = setup
    repo.get_resource.return_value = Agent(id=uuid4(), name="Existing")
    ref = ProjectResourceRef(kind=Kind.AGENT, resource_id=uuid4())
    assert (await service.add(ctx, project_id, [ref])).total == 0
    repo.add.assert_awaited_once_with(
        service.db, project_id=project_id, kind=ref.kind, resource_id=ref.resource_id
    )
    await service.remove(ctx, project_id, ref)
    repo.remove.assert_awaited_once()
    service.projects.get.assert_any_await(ctx, project_id, perm=module.Perm.PROJECTS_EDIT)


async def test_entrypoint_requires_a_visible_linked_workflow(setup, monkeypatch):
    service, ctx, project_id, repo = setup
    with pytest.raises(BadRequestError):
        await service.set_entrypoint(ctx, project_id, uuid4())
    repo.set_entrypoint.assert_not_awaited()
    workflow_id = uuid4()
    listing = module.ProjectResourceList(
        items=[
            module.ProjectResourceRead(
                kind=Kind.WORKFLOW, resource_id=workflow_id, name="Main", is_entrypoint=False
            )
        ],
        total=1,
    )
    monkeypatch.setattr(service, "list_resources", AsyncMock(return_value=listing))
    assert await service.set_entrypoint(ctx, project_id, workflow_id) == listing
    await service.set_entrypoint(ctx, project_id, None)
    assert repo.set_entrypoint.await_args.kwargs["workflow_id"] is None


def test_model_representation():
    assert "ProjectResource" in repr(ProjectResource(id=uuid4(), project_id=uuid4()))
