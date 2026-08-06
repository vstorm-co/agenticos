"""Agent registry routes - the Builder's backend.

Note where the permission checks are, and where they are not. Routes that act on
the *collection* of agents - listing, creating, reading the catalogs - carry a
`require(...)` gate, because there is no specific agent whose grants could
change the answer.

Routes that act on *one* agent deliberately do not. A resource permission cannot
be decided without the resource: a Viewer holding an explicit edit grant on a
single agent is entitled to edit it, and a role-level gate would refuse them
before `resolve_access` ever saw the grant - contradicting the rule the whole
access layer is built on, that a grant widens what a role allows. Those routes
delegate to `AgentRegistryService`, which checks the role scope *and* the
grant, and reports a refusal as "not found" so ids stay unprobeable.

Every endpoint here is part of the public API by design: the Builder UI is one
client of it, and a client's own scripts are another. There is deliberately no
private variant, which is what keeps "the Builder is just another client" true.
"""

import mimetypes
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from app.agents.capabilities import all_capabilities
from app.agents.spec import AgentSpec
from app.api.deps import AgentRegistrySvc, AgentRunnerSvc, Auth, require
from app.core.permissions import Perm
from app.db.models.agent_run import RunSurface
from app.schemas.agent import (
    AgentClone,
    AgentCreate,
    AgentDetail,
    AgentDraftUpdate,
    AgentList,
    AgentPublish,
    AgentRead,
    AgentRollback,
    AgentRunRequest,
    AgentRunResult,
    AgentSpecImport,
    AgentVersionDetail,
    AgentVersionList,
    AgentVersionRead,
    CapabilityCatalog,
    CapabilityCatalogEntry,
    CapabilityToolContract,
    McpCatalog,
    McpCatalogEntry,
    SpecialistPromote,
)
from app.services.capability_contracts import tool_contracts
from app.services.mcp_catalog import CATALOG

router = APIRouter()


@router.get(
    "/capabilities",
    response_model=CapabilityCatalog,
    dependencies=[Depends(require(Perm.AGENTS_VIEW))],
)
async def list_capability_catalog() -> Any:
    """Every capability an agent can be given, with the schema its form is built from."""
    contracts = tool_contracts()
    items = [
        CapabilityCatalogEntry(
            id=definition.id,
            name=definition.name,
            category=definition.category,
            description=definition.description,
            side_effecting=definition.side_effecting,
            tools=list(definition.tools),
            scopes=sorted(definition.scopes),
            contracts=[
                CapabilityToolContract(
                    tool_id=tool_id,
                    description=contract.description,
                    parameters=contract.parameters,
                )
                for tool_id, contract in contracts.get(definition.id, {}).items()
            ],
            config_schema=definition.config_json_schema(),
            requires_secret=definition.secret,
        )
        for definition in all_capabilities()
    ]
    return CapabilityCatalog(items=items, total=len(items))


@router.get(
    "/mcp-catalog",
    response_model=McpCatalog,
    dependencies=[Depends(require(Perm.AGENTS_VIEW))],
)
async def list_mcp_catalog() -> Any:
    """Servers an organization can connect in one click, plus the custom option.

    Hand-curated rather than mirrored from the public registry: each entry is a
    small promise that the auth flow works and the description is honest.
    """
    items = [
        McpCatalogEntry(
            key=entry.key,
            name=entry.name,
            description=entry.description,
            category=entry.category,
            auth=entry.auth.value,
            url=entry.url or None,
            docs_url=entry.docs_url or None,
            token_hint=entry.token_hint or None,
            icon=entry.icon or None,
        )
        for entry in CATALOG
    ]
    return McpCatalog(items=items, total=len(items))


@router.get("", response_model=AgentList, dependencies=[Depends(require(Perm.AGENTS_VIEW))])
async def list_agents(
    service: AgentRegistrySvc,
    ctx: Auth,
    include_archived: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Agents this member can see - their own, plus what was shared with them."""
    items, total = await service.list_agents(
        ctx, include_archived=include_archived, skip=skip, limit=limit
    )
    return AgentList(items=items, total=total)


@router.post(
    "",
    response_model=AgentRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.AGENTS_EDIT))],
)
async def create_agent(data: AgentCreate, service: AgentRegistrySvc, ctx: Auth) -> Any:
    """Create an agent in draft. It cannot run until published."""
    return await service.create(ctx, data.spec)


@router.post(
    "/promote",
    response_model=AgentRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.AGENTS_EDIT))],
)
async def promote_specialist(data: SpecialistPromote, service: AgentRegistrySvc, ctx: Auth) -> Any:
    """Promote a specialist into a draft agent the caller owns.

    A collection route, gated like `create`: promoting creates an agent, and a
    specialist a model invented inside somebody else's run must not become the
    caller's agent without the permission to add one. It does not publish, pin or
    remove anything - each of those is the author's next, separate decision.
    """
    return await service.promote_specialist(
        ctx, data.specialist, fallback_model_profile_id=data.fallback_model_profile_id
    )


@router.get("/{agent_id}", response_model=AgentDetail)
async def get_agent(agent_id: UUID, service: AgentRegistrySvc, ctx: Auth) -> Any:
    """One agent with the spec currently being edited."""
    agent = await service.get(ctx, agent_id)
    return AgentDetail(
        id=agent.id,
        slug=agent.slug,
        name=agent.name,
        description=agent.description,
        status=agent.status,
        visibility=agent.visibility,
        owner_user_id=agent.owner_user_id,
        current_version_id=agent.current_version_id,
        has_avatar=agent.has_avatar,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        draft_spec=AgentSpec.model_validate(agent.draft_spec),
    )


@router.put(
    "/{agent_id}/draft",
    response_model=AgentRead,
)
async def save_draft(
    agent_id: UUID, data: AgentDraftUpdate, service: AgentRegistrySvc, ctx: Auth
) -> Any:
    """Save an edit without making it live. Half-finished specs are allowed here."""
    return await service.save_draft(ctx, agent_id, data.spec)


@router.post(
    "/{agent_id}/validate",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def validate_draft(agent_id: UUID, service: AgentRegistrySvc, ctx: Auth) -> None:
    """Check the draft without publishing - what the Builder calls as you type.

    `agent_id` is passed on so the cycle check can see a delegation loop that
    closes on *this* agent. Without it the Builder would call a draft valid and
    publish would refuse it one round trip later, which is the worst place to
    learn it: the person has already left the form.
    """
    agent = await service.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)
    await service.validate_spec(ctx, AgentSpec.model_validate(agent.draft_spec), agent_id=agent.id)


@router.post(
    "/{agent_id}/publish",
    response_model=AgentVersionRead,
)
async def publish_agent(
    agent_id: UUID, data: AgentPublish, service: AgentRegistrySvc, ctx: Auth
) -> Any:
    """Validate the draft and freeze it as the version that runs."""
    return await service.publish(ctx, agent_id, note=data.note)


@router.post(
    "/{agent_id}/rollback",
    response_model=AgentVersionRead,
)
async def rollback_agent(
    agent_id: UUID, data: AgentRollback, service: AgentRegistrySvc, ctx: Auth
) -> Any:
    """Republish an earlier spec as a new version, keeping history linear."""
    return await service.rollback(ctx, agent_id, to_version_id=data.version_id)


@router.get(
    "/{agent_id}/versions",
    response_model=AgentVersionList,
)
async def list_versions(agent_id: UUID, service: AgentRegistrySvc, ctx: Auth) -> Any:
    """Publication history, newest first."""
    items = await service.list_versions(ctx, agent_id)
    return AgentVersionList(items=items, total=len(items))


@router.get(
    "/{agent_id}/versions/{version_id}",
    response_model=AgentVersionDetail,
)
async def get_version(
    agent_id: UUID, version_id: UUID, service: AgentRegistrySvc, ctx: Auth
) -> Any:
    """One version with the spec it froze - what a diff is read from."""
    version = await service.get_version(ctx, agent_id, version_id)
    return AgentVersionDetail(
        id=version.id,
        version=version.version,
        note=version.note,
        published_by_user_id=version.published_by_user_id,
        created_at=version.created_at,
        spec=AgentSpec.model_validate(version.spec),
    )


@router.get(
    "/{agent_id}/spec.yaml",
    response_class=Response,
)
async def export_spec(agent_id: UUID, service: AgentRegistrySvc, ctx: Auth) -> Response:
    """Export the draft as YAML for the client's own git repository.

    The file carries references, never secrets - which is what makes committing
    it safe and what backs the platform's anti-lock-in promise.
    """
    agent = await service.get(ctx, agent_id)
    spec = AgentSpec.model_validate(agent.draft_spec)
    return Response(
        content=spec.to_yaml(),
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{agent.slug}.yaml"'},
    )


@router.post(
    "/{agent_id}/spec.yaml",
    response_model=AgentRead,
)
async def import_spec(
    agent_id: UUID, data: AgentSpecImport, service: AgentRegistrySvc, ctx: Auth
) -> Any:
    """Replace the draft with a hand-written or externally-managed spec."""
    return await service.save_draft(ctx, agent_id, AgentSpec.from_yaml(data.yaml))


@router.post(
    "/{agent_id}/clone",
    response_model=AgentRead,
    status_code=status.HTTP_201_CREATED,
)
async def clone_agent(
    agent_id: UUID, data: AgentClone, service: AgentRegistrySvc, ctx: Auth
) -> Any:
    """Copy an agent's draft into a new agent, in draft.

    No role gate, like every other route that names one agent: whether the
    caller may read *this* one depends on its grants. That cloning also creates
    is checked in the service, which is the only place that knows both halves.
    """
    return await service.clone(ctx, agent_id, name=data.name)


@router.post(
    "/{agent_id}/avatar",
    response_model=AgentRead,
)
async def upload_agent_avatar(
    agent_id: UUID,
    service: AgentRegistrySvc,
    ctx: Auth,
    file: UploadFile = File(...),
) -> Any:
    """Give the agent a picture, or replace the one it has."""
    return await service.set_avatar(
        ctx,
        agent_id,
        file_data=await file.read(),
        filename=file.filename or "avatar.jpg",
        content_type=file.content_type,
    )


@router.get(
    "/{agent_id}/avatar",
    response_class=FileResponse,
    response_model=None,
)
async def get_agent_avatar(agent_id: UUID, service: AgentRegistrySvc, ctx: Auth) -> FileResponse:
    """Stream the agent's picture to someone entitled to see the agent."""
    path = await service.avatar_path(ctx, agent_id)
    media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return FileResponse(path=path, media_type=media_type)


@router.post(
    "/{agent_id}/archive",
    response_model=AgentRead,
)
async def archive_agent(agent_id: UUID, service: AgentRegistrySvc, ctx: Auth) -> Any:
    """Retire an agent, keeping its history and its runs."""
    return await service.archive(ctx, agent_id)


@router.post(
    "/{agent_id}/unarchive",
    response_model=AgentRead,
)
async def unarchive_agent(agent_id: UUID, service: AgentRegistrySvc, ctx: Auth) -> Any:
    """Bring a retired agent back to draft, or to published if it has a version."""
    return await service.unarchive(ctx, agent_id)


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_agent(agent_id: UUID, service: AgentRegistrySvc, ctx: Auth) -> None:
    """Permanently remove an agent, its versions and its shares."""
    await service.delete(ctx, agent_id)


@router.post(
    "/{agent_id}/run",
    response_model=AgentRunResult,
)
async def run_agent(
    agent_id: UUID,
    data: AgentRunRequest,
    service: AgentRunnerSvc,
    ctx: Auth,
) -> Any:
    """Run a published agent and return its answer.

    The non-streaming path. It goes through the same runner as every other
    surface, so the run is recorded, the budget applies, and the cost lands in
    the same dashboard - an API caller cannot route around governance by not
    using the UI.
    """
    output, run = await service.execute(
        ctx,
        agent_id,
        data.prompt,
        surface=RunSurface.API,
        conversation_id=data.conversation_id,
        environment_id=data.environment_id,
    )
    return AgentRunResult(
        run_id=run.id,
        output=output,
        status=run.status,
        cost_usd=run.cost_usd,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
    )
