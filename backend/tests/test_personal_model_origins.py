"""Personal model connections follow the run's owner and verified origin.

The resolver's credential checks live in test_personal_model_connections. These
tests cover the boundaries that must carry the right identity to that resolver,
before a request can decrypt a personal credential or build a model client.
"""

from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import replace
from typing import NoReturn
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from starlette.requests import Request

from app.agents.audience import RunAudience
from app.agents.model_resolver import ModelRequestSpec
from app.agents.spec import AgentSpec, SubagentRef
from app.agents.subagent_runtime import DelegationStash
from app.api.deps import get_auth_context, get_path_org_context
from app.core.audit import current_impersonator, set_impersonator
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import AgentStatus
from app.db.models.agent_run import RunStatus, RunSurface
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services.agent_chat import ChatAgentRunner
from app.services.agent_runner import (
    AgentRunnerService,
    _Delegation,
    _RunBudget,
    _TestConnections,
)
from app.services.mcp_connection import ResolvedMcpToolsets
from app.services.workflow_execution import context as workflow_context

pytestmark = [pytest.mark.anyio, pytest.mark.security]

RUNNER = "app.services.agent_runner"


@pytest.fixture(autouse=True)
def _clean_impersonator() -> Iterator[None]:
    previous = current_impersonator()
    set_impersonator(None)
    try:
        yield
    finally:
        set_impersonator(previous)


def _owner() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)


@pytest.mark.parametrize("surface", ["active_organization", "path_organization", "chat"])
@pytest.mark.parametrize("impersonated", [False, True])
async def test_session_context_keeps_verified_impersonation(
    surface: str, impersonated: bool
) -> None:
    owner = _owner()
    user = User(
        id=owner.user_id,
        email="owner@example.test",
        full_name="Owner",
        is_app_admin=False,
    )
    org = Organization(id=owner.organization_id)
    membership = OrganizationMember(organization_id=org.id, user_id=user.id, role=owner.role)
    request = Request({"type": "http", "headers": []})
    db = MagicMock()
    if impersonated:
        set_impersonator(uuid4())

    with (
        patch("app.api.deps._member_repo.get", new=AsyncMock(return_value=membership)),
        patch("app.services.agent_chat.member_repo.get", new=AsyncMock(return_value=membership)),
    ):
        if surface == "active_organization":
            ctx = await get_auth_context(request, user, org, db)
        elif surface == "path_organization":
            ctx = await get_path_org_context(org.id, request, user, db)
        else:
            ctx = await ChatAgentRunner(db)._context(user, org.id)

    assert ctx.user_id == user.id
    assert ctx.organization_id == org.id
    assert ctx.is_impersonated is impersonated
    assert ctx.personal_user_id == (None if impersonated else user.id)


class _OwnerConnectionResolved(Exception):
    """Stop at the model boundary without building or calling a provider."""


def _dispatch(
    ctx: AuthContext, *, public_origin: bool = False, impersonated: bool = False
) -> workflow_context.DispatchContext:
    return workflow_context.DispatchContext(
        organization_id=ctx.organization_id,
        workflow_run_id=uuid4(),
        node_run_id=uuid4(),
        node_instance_id=uuid4(),
        attempt_no=1,
        auth=ctx,
        resumed_agent_run_id=None,
        public_origin=public_origin,
        impersonated=impersonated,
    )


@pytest.mark.parametrize(
    "origin",
    [
        "own_session",
        "context_impersonation",
        "audit_impersonation",
        "persisted_impersonation",
        "workflow_impersonation",
        "public_workflow",
        "unknown_workflow",
        "explicit_public_origin",
        "private_workflow",
        "nested_workflow",
        "context_workflow",
        "persisted_workflow",
    ],
)
@pytest.mark.parametrize("resumed", [False, True])
async def test_origin_is_checked_before_the_first_model_resolution(
    origin: str, resumed: bool
) -> None:
    owner = _owner()
    ctx = replace(
        owner,
        user_id=uuid4() if resumed else owner.user_id,
        is_impersonated=origin == "context_impersonation",
        is_workflow=origin == "context_workflow",
    )
    service = AgentRunnerService(MagicMock())
    spec = AgentSpec(name="Personal assistant", model_profile_id=uuid4())
    workflow = origin in {
        "workflow_impersonation",
        "public_workflow",
        "unknown_workflow",
        "private_workflow",
    }
    dispatch = (
        _dispatch(
            ctx,
            public_origin=origin == "public_workflow",
            impersonated=origin == "workflow_impersonation",
        )
        if (workflow or origin == "nested_workflow") and origin != "unknown_workflow"
        else None
    )
    seen: list[AuthContext] = []

    async def resolve(models_ctx: AuthContext, *, profile_id: UUID | None) -> NoReturn:
        assert profile_id == spec.model_profile_id
        seen.append(models_ctx)
        if models_ctx.personal_user_id is None:
            raise AuthorizationError(message="A personal connection needs its own signed-in user")
        assert models_ctx.personal_user_id == owner.user_id
        raise _OwnerConnectionResolved

    if origin == "audit_impersonation":
        set_impersonator(uuid4())
    allowed = origin == "own_session"
    expected = _OwnerConnectionResolved if allowed else AuthorizationError
    with (
        patch(f"{RUNNER}.RoutineAuthority.capture", new=AsyncMock(return_value=None)),
        patch.object(service.registry, "with_assistant_guidance", new=AsyncMock(return_value=spec)),
        patch.object(service.models, "resolve", new=AsyncMock(side_effect=resolve)),
        workflow_context.dispatching_as(dispatch) if dispatch is not None else nullcontext(),
        pytest.raises(expected),
    ):
        await service._assemble(
            ctx,
            agent=MagicMock(id=uuid4(), kind="agent", system_key=None, current_version_id=None),
            spec=spec,
            existing_run=MagicMock(id=uuid4()) if resumed else None,
            surface=RunSurface.WORKFLOW if workflow else RunSurface.WEB,
            conversation_id=None,
            user_name=None,
            restored_audience=RunAudience(user_id=owner.user_id) if resumed else None,
            extra_toolsets=None,
            exposure=None,
            decided={},
            resuming={},
            already_spent={},
            already_started={},
            public_origin=origin == "explicit_public_origin",
            impersonated=origin == "persisted_impersonation",
            is_workflow=origin == "persisted_workflow",
        )

    assert len(seen) == 1
    assert seen[0].user_id == owner.user_id
    assert seen[0].personal_user_id == (owner.user_id if allowed else None)
    assert seen[0].is_workflow is (
        workflow or origin in {"nested_workflow", "context_workflow", "persisted_workflow"}
    )
    if origin in {"private_workflow", "nested_workflow", "context_workflow", "persisted_workflow"}:
        assert seen[0].subject_is_publisher_fallback is False


@pytest.mark.parametrize("stored_workflow", [False, True])
async def test_a_parked_nested_workflow_keeps_its_origin_without_a_live_dispatch(
    stored_workflow: bool,
) -> None:
    """The resume's surface and approver cannot replace the original dispatch provenance."""
    owner = _owner()
    service = AgentRunnerService(MagicMock())
    spec = AgentSpec(name="Nested assistant", model_profile_id=uuid4())
    run = MagicMock(
        id=uuid4(),
        user_id=owner.user_id,
        status=RunStatus.AWAITING_APPROVAL.value,
        surface=RunSurface.WEB.value,
        conversation_id=None,
        exposure_id=None,
        environment_id=None,
        paused_state={
            "messages": [],
            "tool_call_ids": {},
            "admitted_as": {
                "audience_user_id": str(owner.user_id),
                "is_workflow": stored_workflow,
            },
        },
    )
    seen: list[AuthContext] = []

    async def resolve(ctx: AuthContext, *, profile_id: UUID | None) -> NoReturn:
        assert profile_id == spec.model_profile_id
        seen.append(ctx)
        if ctx.personal_user_id is None:
            raise AuthorizationError(message="Workflow execution cannot use a personal connection")
        raise _OwnerConnectionResolved

    expected = AuthorizationError if stored_workflow else _OwnerConnectionResolved
    with (
        patch(f"{RUNNER}.agent_run_repo.claim_parked_run", new=AsyncMock(return_value=run)),
        patch.object(
            service,
            "_decisions",
            new=AsyncMock(
                return_value=({}, MagicMock(delegations={}, spent={}, started={}, specialists={}))
            ),
        ),
        patch.object(
            service,
            "_parked_spec",
            new=AsyncMock(
                return_value=(
                    MagicMock(id=uuid4(), kind="agent", system_key=None, current_version_id=None),
                    spec,
                )
            ),
        ),
        patch.object(service, "_with_environment_observability", new=AsyncMock(return_value=spec)),
        patch(f"{RUNNER}.restore_directory", new=AsyncMock(return_value=None)),
        patch(f"{RUNNER}.RoutineAuthority.capture", new=AsyncMock(return_value=None)),
        patch.object(service.registry, "with_assistant_guidance", new=AsyncMock(return_value=spec)),
        patch.object(service.models, "resolve", new=AsyncMock(side_effect=resolve)),
        pytest.raises(expected),
    ):
        await service.resume(replace(owner, user_id=uuid4()), run.id)

    assert len(seen) == 1
    assert seen[0].user_id == owner.user_id
    assert seen[0].is_workflow is stored_workflow
    assert seen[0].subject_is_publisher_fallback is False
    assert seen[0].personal_user_id == (None if stored_workflow else owner.user_id)


def _delegation(owner: AuthContext) -> _Delegation:
    """An approver continues a run belonging to a different person."""
    return _Delegation(
        ctx=replace(owner, user_id=uuid4()),
        models_ctx=owner,
        run=MagicMock(id=uuid4()),
        surface=RunSurface.WEB,
        agent_id=uuid4(),
        user_id=str(owner.user_id),
        user_name=None,
        personal_mcp_user_id=owner.user_id,
        personal_apps_allowed=True,
        sender_present=True,
        approvals=MagicMock(),
        budget=_RunBudget(),
        render_variables=lambda spec: spec,
        record=AsyncMock(),
        queued=[],
        recorders=[],
        attribution={},
        runtimes=[],
        stash=DelegationStash(),
        test_connections=_TestConnections(),
        isolation=None,
    )


def _profile(owner: AuthContext, label: str) -> ModelProfile:
    return ModelProfile(
        id=uuid4(),
        organization_id=owner.organization_id,
        label=label,
        provider="openai",
        model="gpt-4.1",
        base_url=None,
        fallback_profile_ids=[],
        params={},
        personal_owner_user_id=owner.user_id,
    )


async def test_a_resumed_dynamic_catalog_offers_the_owners_personal_model() -> None:
    owner = _owner()
    delegation = _delegation(owner)
    owned_profile = _profile(owner, "Owner's model")
    approver_profile = _profile(delegation.ctx, "Approver's model")
    resolved = MagicMock(spec=ModelRequestSpec)
    service = AgentRunnerService(MagicMock())
    listed_for: list[UUID | None] = []

    async def list_profiles(ctx: AuthContext) -> list[ModelProfile]:
        listed_for.append(ctx.personal_user_id)
        return [owned_profile] if ctx.personal_user_id == owner.user_id else [approver_profile]

    async def resolve(ctx: AuthContext, *, profile_id: UUID | None) -> ModelRequestSpec:
        if ctx.personal_user_id != owner.user_id or profile_id != owned_profile.id:
            raise AuthorizationError(message="That personal model belongs to another user")
        return resolved

    with (
        patch.object(service.models, "list_profiles", new=AsyncMock(side_effect=list_profiles)),
        patch.object(
            service.models, "resolve", new=AsyncMock(side_effect=resolve)
        ) as resolve_model,
    ):
        unnamed = await service._model_catalog(delegation, named=frozenset())
        resolve_model.assert_not_awaited()
        offered = await service._model_catalog(delegation, named=frozenset({owned_profile.id}))
        offered_again = await service._model_catalog(
            delegation, named=frozenset({owned_profile.id})
        )
        unnamed_again = await service._model_catalog(delegation, named=frozenset())

    assert unnamed == unnamed_again == {}
    assert offered == {"Owner's model": resolved}
    assert offered_again == offered
    assert listed_for == [owner.user_id]
    resolve_model.assert_awaited_once()


async def test_a_resumed_delegates_review_uses_the_owners_personal_connection() -> None:
    owner = _owner()
    delegation = _delegation(owner)
    service = AgentRunnerService(MagicMock())
    main_profile, reviewer_profile = uuid4(), uuid4()
    spec = AgentSpec(
        name="Researcher",
        model_profile_id=main_profile,
        reviewers=[
            {"name": "sources", "model_profile_id": str(reviewer_profile), "instructions": "Check."}
        ],
    )
    ref = SubagentRef(agent_id=uuid4(), agent_version_id=uuid4())
    delegate = MagicMock(
        id=ref.agent_id,
        slug="researcher",
        status=AgentStatus.PUBLISHED.value,
        kind="agent",
        system_key=None,
        current_version_id=None,
    )
    version = MagicMock(id=ref.agent_version_id, agent_id=ref.agent_id)
    version.spec = spec.model_dump(mode="json")
    main_model = MagicMock(spec=ModelRequestSpec)
    reviewer_model = MagicMock(spec=ModelRequestSpec)
    resolved_for: list[tuple[UUID | None, UUID | None]] = []

    async def resolve(ctx: AuthContext, *, profile_id: UUID | None) -> ModelRequestSpec:
        resolved_for.append((ctx.personal_user_id, profile_id))
        if ctx.personal_user_id != owner.user_id:
            raise AuthorizationError(message="That personal connection belongs to the run's owner")
        return reviewer_model if profile_id == reviewer_profile else main_model

    with (
        patch(f"{RUNNER}.agent_repo.get", new=AsyncMock(return_value=delegate)),
        patch(f"{RUNNER}.agent_repo.get_version", new=AsyncMock(return_value=version)),
        patch.object(service.registry, "with_assistant_guidance", new=AsyncMock(return_value=spec)),
        patch.object(
            service,
            "_delegate_resources",
            new=AsyncMock(return_value={"kb_collection_names": [], "kb_vector_scopes": {}}),
        ),
        patch.object(service.models, "resolve", new=AsyncMock(side_effect=resolve)),
        patch.object(service, "_platform_credential", new=AsyncMock(return_value=None)),
        patch(
            f"{RUNNER}.build_toolsets_for_agent",
            new=AsyncMock(return_value=ResolvedMcpToolsets(toolsets=[], unavailable=[])),
        ),
        patch.object(service.secrets, "resolve_for_bindings", new=AsyncMock(return_value={})),
        patch(f"{RUNNER}._delegate_builder") as build,
    ):
        result = await service._resolve_delegate(
            delegation,
            ref=ref,
            shared=[],
            resources={},
            depth_remaining=0,
            depth=1,
            ancestors=frozenset(),
        )

    assert result.name == "researcher"
    assert build.call_args.kwargs["reviewer_models"] == {reviewer_profile: reviewer_model}
    assert resolved_for == [(owner.user_id, main_profile), (owner.user_id, reviewer_profile)]
