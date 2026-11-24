"""The preset installs one reviewed, project-bound agent/routine and real task views."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.db.models.agent import Agent
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.conversation import Conversation
from app.db.models.credential import ModelProfile
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.table_view import TableView
from app.db.models.virtual_table import VirtualTable
from app.schemas.project import ProjectCreate
from app.schemas.project_tracking import ProjectTrackingCreate
from app.services.agent_registry import AgentRegistryService
from app.services.project import ProjectService
from app.services.project_tracking import ProjectTrackingService
from app.services.routine_sources import read_policy
from tests.integration.workflow_run_support import seed_member

pytestmark = pytest.mark.anyio


async def seed(db: AsyncSession) -> tuple[AuthContext, UUID, UUID, UUID]:
    user, org = await seed_member(db)
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    sealed = seal_secret(
        ApiKeySecret(api_key="sk-test-project-tracker"), scope=VaultScope.organization(org.id)
    )
    secret = OrganizationSecret(
        organization_id=org.id,
        name="Model key",
        purpose="openai",
        visibility="org",
        kind=SecretKind.API_KEY.value,
        sealed_secret=sealed.ciphertext,
        hint=sealed.hint,
    )
    db.add(secret)
    await db.flush()
    profile = ModelProfile(
        organization_id=org.id,
        label="Test model",
        provider="openai",
        model="gpt-4.1",
        secret_id=secret.id,
    )
    db.add(profile)
    await db.flush()
    registry = AgentRegistryService(db)
    agent = await registry.create(
        ctx,
        AgentSpec(
            name=f"Planner {uuid4().hex[:6]}",
            instructions="Plan from verified evidence.",
            model_profile_id=profile.id,
        ),
    )
    version = await registry.publish(ctx, agent.id)
    project = await ProjectService(db).create(ctx, ProjectCreate(name="Launch", backend="state"))
    return ctx, project.id, agent.id, version.id


async def request(
    db: AsyncSession, ctx: AuthContext, project: UUID, agent: UUID, version: UUID
) -> ProjectTrackingCreate:
    offered = await ProjectTrackingService(db).review(
        ctx, project, agent_id=agent, version_id=version
    )
    return ProjectTrackingCreate(
        base_agent_id=agent,
        base_version_id=version,
        source_review_token=offered.review_token,
        publish_and_start=True,
        agent_name="Launch tracker",
        table_name="Launch tasks",
    )


@pytest.mark.parametrize("existing_name", [False, True])
async def test_preset_creates_real_views_private_copy_and_project_conversation(
    db: AsyncSession, existing_name
):
    ctx, project, agent, version = await seed(db)
    service = ProjectTrackingService(db)
    assert await service.get(ctx, project) is None
    data = await request(db, ctx, project, agent, version)
    if existing_name:
        from app.schemas.task import BoardEnsure
        from app.services.tasks import TaskService
        from app.services.virtual_tables import VirtualTableService

        board = await TaskService(db).ensure_board(
            ctx, BoardEnsure(scope="project", scope_id=project)
        )
        table = await VirtualTableService(db).describe_table(ctx, board.table_id)
        data = data.model_copy(update={"table_name": table.name})
    installed = await service.create(ctx, project, data)
    clone = await db.get(Agent, installed.agent_id)
    original = await db.get(Agent, agent)
    trigger = await db.get(AgentTrigger, installed.trigger_id)
    conversation = await db.get(Conversation, installed.conversation_id)
    assert clone is not None and clone.id != agent and clone.visibility == "private"
    assert original is not None and original.current_version_id == version
    assert (
        trigger is not None
        and trigger.project_id == project
        and trigger.runs_as_creator
        and trigger.is_active
    )
    assert trigger.pinned_version_id == installed.agent_version_id
    assert conversation is not None and conversation.project_id == project
    policy = read_policy(trigger.approved_sources)
    assert policy.project_id == project and policy.project_hash is not None
    assert all(item["id"] != "virtual_tables" for item in clone.draft_spec["capabilities"])
    assert clone.draft_spec["table_bindings"] == [
        {"table_id": str(installed.table_id), "operations": ["read", "create", "update"]}
    ]
    assert any(item["account"] == "platform" for item in clone.draft_spec["mcp_servers"])
    views = list(
        await db.scalars(select(TableView).where(TableView.table_id == installed.table_id))
    )
    assert {view.name for view in views} == {
        "All tasks",
        "Board",
        "Open tasks",
        "Blocked",
        "Planned",
        "Waiting for review",
        "Agent tasks",
    }
    assert {view.kind for view in views} == {"table", "kanban", "list"}
    assert all(view.visibility == "shared" for view in views)
    assert (await db.get(VirtualTable, installed.table_id)).visibility == "private"
    assert await service.get(ctx, project) == installed


async def test_identical_retry_reuses_every_resource_but_changed_input_conflicts(db: AsyncSession):
    ctx, project, agent, version = await seed(db)
    service = ProjectTrackingService(db)
    data = await request(db, ctx, project, agent, version)
    installed = await service.create(ctx, project, data)
    assert await service.create(ctx, project, data) == installed
    assert await db.scalar(select(func.count()).select_from(VirtualTable)) == 1
    assert await db.scalar(select(func.count()).select_from(AgentTrigger)) == 1
    with pytest.raises(ConflictError):
        await service.create(ctx, project, data.model_copy(update={"interval_seconds": 3600}))


async def test_changed_workspace_invalidates_review_before_creating_resources(db: AsyncSession):
    from app.db.models.project import Project

    ctx, project, agent, version = await seed(db)
    data = await request(db, ctx, project, agent, version)
    row = await db.get(Project, project)
    assert row is not None
    row.workspace_generation = uuid4()
    await db.flush()
    with pytest.raises(ConflictError):
        await ProjectTrackingService(db).create(ctx, project, data)
    assert await db.scalar(select(func.count()).select_from(VirtualTable)) == 0
    assert await db.scalar(select(func.count()).select_from(AgentTrigger)) == 0


@pytest.mark.security
@pytest.mark.parametrize("identity", ["api", "routine", "foreign", "no-create"])
async def test_preset_refuses_unattended_cross_tenant_and_unentitled_callers(
    db: AsyncSession, identity: str
):
    ctx, project, agent, version = await seed(db)
    if identity == "api":
        ctx = replace(ctx, api_key_id=uuid4())
    elif identity == "routine":
        ctx = replace(ctx, routine_id=uuid4())
    elif identity == "foreign":
        user, org = await seed_member(db)
        ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    else:
        ctx = replace(ctx, role="viewer")
    with pytest.raises((AuthorizationError, NotFoundError)):
        await ProjectTrackingService(db).review(ctx, project, agent_id=agent, version_id=version)


async def test_publication_is_explicit_in_the_request_contract():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ProjectTrackingCreate(
            base_agent_id=uuid4(),
            base_version_id=uuid4(),
            source_review_token="a" * 64,
            publish_and_start=False,
            agent_name="Tracker",
            table_name="Tasks",
        )


async def test_project_binding_refuses_another_workspace_and_live_project_retargeting(
    db: AsyncSession,
):
    from app.db.models.project import Project
    from app.services.routine_authority import RoutineAuthority
    from app.services.routine_sources import RoutineSourcesRequired

    ctx, project_id, agent, version = await seed(db)
    installed = await ProjectTrackingService(db).create(
        ctx, project_id, await request(db, ctx, project_id, agent, version)
    )
    trigger = await db.get(AgentTrigger, installed.trigger_id)
    project = await db.get(Project, project_id)
    assert trigger is not None and project is not None
    policy = read_policy(trigger.approved_sources)
    authority = await RoutineAuthority.capture(
        db,
        replace(
            ctx,
            routine_id=trigger.id,
            routine_source_policy_id=policy.id,
            fired_as_creator="schedule",
        ),
        agent_id=installed.agent_id,
        run=None,
    )
    assert authority is not None
    authority.require_project(project)
    other = await ProjectService(db).create(ctx, ProjectCreate(name="Other", backend="state"))
    with pytest.raises(RoutineSourcesRequired):
        authority.require_project(other)
    with pytest.raises(RoutineSourcesRequired):
        authority.require_project(None)
    project.workspace_generation = uuid4()
    await db.flush()
    with pytest.raises(RoutineSourcesRequired):
        await authority.check_in(db, installed.agent_id)


async def test_lost_project_grant_refuses_the_next_routine_tool_as_authorization(db: AsyncSession):
    from app.db.models.organization import OrganizationMember
    from app.db.models.project import Project
    from app.db.models.resource_grant import ResourceGrant
    from app.db.models.user import User
    from app.services.routine_authority import RoutineAuthority

    ctx, project_id, agent, version = await seed(db)
    installed = await ProjectTrackingService(db).create(
        ctx, project_id, await request(db, ctx, project_id, agent, version)
    )
    other_owner = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add(other_owner)
    await db.flush()
    project = await db.get(Project, project_id)
    trigger = await db.get(AgentTrigger, installed.trigger_id)
    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == ctx.organization_id,
            OrganizationMember.user_id == ctx.user_id,
        )
    )
    assert project is not None and trigger is not None and member is not None
    project.owner_user_id = other_owner.id
    member.role = "viewer"
    grant = ResourceGrant(
        organization_id=ctx.organization_id,
        resource_type="project",
        resource_id=project_id,
        subject_user_id=ctx.user_id,
        level="use",
    )
    db.add_all(
        [
            grant,
            ResourceGrant(
                organization_id=ctx.organization_id,
                resource_type="agent",
                resource_id=installed.agent_id,
                subject_user_id=ctx.user_id,
                level="use",
            ),
        ]
    )
    await db.flush()
    policy = read_policy(trigger.approved_sources)
    actor = replace(
        ctx,
        role="viewer",
        routine_id=trigger.id,
        routine_source_policy_id=policy.id,
        fired_as_creator="schedule",
    )
    authority = await RoutineAuthority.capture(db, actor, agent_id=installed.agent_id, run=None)
    assert authority is not None
    await db.delete(grant)
    await db.flush()
    with pytest.raises(AuthorizationError):
        await authority.check_in(db, installed.agent_id)


async def test_project_notification_is_rechecked_after_project_access_is_revoked(db: AsyncSession):
    from app.db.models.notification import Notification, NotificationEventType
    from app.db.models.project import Project
    from app.services.notification_center import NotificationCenterService

    ctx, project_id, _, _ = await seed(db)
    project = await db.get(Project, project_id)
    assert project is not None
    notification = Notification(
        organization_id=ctx.organization_id,
        recipient_user_id=ctx.user_id,
        event_type=NotificationEventType.RUN_COMPLETED.value,
        occurrence_id=str(uuid4()),
        summary="Private project report",
        render_context={"project_id": str(project_id)},
    )
    db.add(notification)
    await db.flush()
    center = NotificationCenterService(db)
    assert (await center.gate_for(ctx, notification)).visible
    viewer = replace(ctx, role="viewer")
    # A private project with another owner is no longer readable without a grant.
    project.owner_user_id = None
    await db.flush()
    assert not (await center.gate_for(viewer, notification)).visible
    notification.render_context = {"project_id": str(uuid4())}
    assert not (await center.gate_for(ctx, notification)).visible
    notification.render_context = {"project_id": "invalid"}
    assert not (await center.gate_for(ctx, notification)).visible


async def test_personal_export_includes_tracker_links_without_request_hash(db: AsyncSession):
    from app.services.personal_data import PersonalDataService

    ctx, project, agent, version = await seed(db)
    installed = await ProjectTrackingService(db).create(
        ctx, project, await request(db, ctx, project, agent, version)
    )
    exported = await PersonalDataService(db).export(ctx.subject_id, actor_user_id=ctx.subject_id)
    assert len(exported.project_trackers) == 1
    assert exported.project_trackers[0].table_id == installed.table_id
    assert "request_hash" not in exported.project_trackers[0].model_dump()


async def test_workspace_change_during_installation_rolls_back_the_whole_preset(
    db: AsyncSession, monkeypatch
):
    from app.db.models.project import Project
    from app.services.agent_trigger import AgentTriggerService

    ctx, project, agent, version = await seed(db)
    data = await request(db, ctx, project, agent, version)
    original_create = AgentTriggerService.create

    async def changed_create(self, actor, agent_id, trigger_data):
        row = await db.get(Project, project)
        assert row is not None
        row.workspace_generation = uuid4()
        await db.flush()
        return await original_create(self, actor, agent_id, trigger_data)

    monkeypatch.setattr(AgentTriggerService, "create", changed_create)
    with pytest.raises(ConflictError):
        async with db.begin_nested():
            await ProjectTrackingService(db).create(ctx, project, data)
    assert await db.scalar(select(func.count()).select_from(VirtualTable)) == 0
    assert await db.scalar(select(func.count()).select_from(AgentTrigger)) == 0


async def test_missing_trigger_is_not_a_successful_installation(db: AsyncSession):
    from app.db.models.project_tracking import ProjectTracking

    ctx, project, agent, version = await seed(db)
    row = ProjectTracking(
        id=uuid4(),
        organization_id=ctx.organization_id,
        project_id=project,
        user_id=ctx.user_id,
        agent_id=agent,
        agent_version_id=version,
        table_id=uuid4(),
        trigger_id=uuid4(),
        request_hash="secret-not-in-repr",
    )
    assert "secret-not-in-repr" not in repr(row)
    with pytest.raises(NotFoundError):
        await ProjectTrackingService(db)._read(ctx, row)


@pytest.mark.security
async def test_tracker_refuses_a_secret_rotated_during_trigger_admission(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.agent_trigger import AgentTriggerService

    ctx, project, agent, version = await seed(db)
    data = await request(db, ctx, project, agent, version)
    create = AgentTriggerService.create

    async def rotated(service, *args, **kwargs):
        trigger = await create(service, *args, **kwargs)
        policy = read_policy(trigger.approved_sources)
        changed = policy.model_copy(update={"secret_sources": {uuid4(): uuid4()}})
        assert changed.secret_sources != policy.secret_sources
        trigger.approved_sources = changed.model_dump(mode="json")
        return trigger

    monkeypatch.setattr(AgentTriggerService, "create", rotated)
    with pytest.raises(ConflictError, match="source changed"):
        await ProjectTrackingService(db).create(ctx, project, data)


async def test_project_deletion_erases_memory_descendants_and_deregisters_its_webhooks(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from app.core.memory_keys import organization_owner_key, project_owner_key
    from app.repositories import memory_claim as memory_repo
    from app.repositories.memory_claim import ClaimScope
    from app.services.agent_trigger import AgentTriggerService
    from app.services.memory import claims

    ctx, project, agent, version = await seed(db)
    data = await request(db, ctx, project, agent, version)
    installed = await ProjectTrackingService(db).create(ctx, project, data)
    source = (
        await claims.remember(
            db,
            organization_id=ctx.organization_id,
            scope=ClaimScope(project_owner_key(project), agent),
            statement="Project-specific secret plan",
        )
    ).claim
    shared = await claims.share(
        db,
        claim=source,
        to=ClaimScope(organization_owner_key(ctx.organization_id), None),
        author_user_id=ctx.subject_id,
    )
    remove = AsyncMock()
    monkeypatch.setattr(AgentTriggerService, "_deregister_webhook", remove)
    await ProjectService(db).delete(ctx, project)
    assert (
        await memory_repo.get(db, organization_id=ctx.organization_id, claim_id=source.id) is None
    )
    assert (
        await memory_repo.get(db, organization_id=ctx.organization_id, claim_id=shared.id) is None
    )
    remove.assert_awaited_once()
    assert remove.await_args.args[1].id == installed.trigger_id
    assert await db.get(AgentTrigger, installed.trigger_id, populate_existing=True) is None


async def test_a_tracker_is_not_published_onto_an_archived_board(db: AsyncSession):
    from app.schemas.task import BoardEnsure
    from app.services.tasks import TaskService
    from app.services.virtual_tables import VirtualTableService

    ctx, project, agent, version = await seed(db)
    data = await request(db, ctx, project, agent, version)
    board = await TaskService(db).ensure_board(ctx, BoardEnsure(scope="project", scope_id=project))
    await VirtualTableService(db).archive_table(ctx, board.table_id)

    with pytest.raises(ConflictError, match="archived"):
        await ProjectTrackingService(db).create(ctx, project, data)

    assert await db.scalar(select(func.count()).select_from(AgentTrigger)) == 0
