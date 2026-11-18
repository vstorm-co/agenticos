"""Owner-scoped browser procedure capture, review and proposal routes."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    Auth,
    BrowserProcedureTeachingDraftSvc,
    BrowserProcedureTeachingPolicySvc,
    BrowserProcedureTeachingSvc,
    no_store_response,
    require,
)
from app.api.routes.v1._browser_procedure_teaching_http import Revision, with_etag
from app.core.permissions import Perm
from app.schemas.browser_procedure_teaching import (
    BrowserProcedureTeachingChange,
    BrowserProcedureTeachingList,
    BrowserProcedureTeachingPolicyRead,
    BrowserProcedureTeachingPolicyWrite,
    BrowserProcedureTeachingPreferenceRead,
    BrowserProcedureTeachingPreferenceWrite,
    BrowserProcedureTeachingPropose,
    BrowserProcedureTeachingRead,
    BrowserProcedureTeachingStart,
)

router = APIRouter(dependencies=[Depends(no_store_response)])


@router.post(
    "/browser-procedures/teachings",
    response_model=BrowserProcedureTeachingRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.SKILLS_EDIT))],
)
async def start_new(
    data: BrowserProcedureTeachingStart,
    ctx: Auth,
    service: BrowserProcedureTeachingSvc,
    response: Response,
) -> BrowserProcedureTeachingRead:
    return with_etag(response, await service.start(ctx, data))


@router.post(
    "/skills/{skill_id}/browser-procedures/teachings",
    response_model=BrowserProcedureTeachingRead,
    status_code=status.HTTP_201_CREATED,
)
async def start_for_skill(
    skill_id: UUID,
    data: BrowserProcedureTeachingStart,
    ctx: Auth,
    service: BrowserProcedureTeachingSvc,
    response: Response,
) -> BrowserProcedureTeachingRead:
    return with_etag(response, await service.start(ctx, data, skill_id=skill_id))


@router.get("/browser-procedures/teachings", response_model=BrowserProcedureTeachingList)
async def list_sessions(
    ctx: Auth,
    service: BrowserProcedureTeachingSvc,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> Any:
    return await service.list(ctx, limit=limit, cursor=cursor)


@router.get(
    "/browser-procedures/teachings/{session_id}", response_model=BrowserProcedureTeachingRead
)
async def read_session(
    session_id: UUID,
    ctx: Auth,
    service: BrowserProcedureTeachingSvc,
    response: Response,
) -> BrowserProcedureTeachingRead:
    return with_etag(response, await service.get(ctx, session_id))


@router.patch(
    "/browser-procedures/teachings/{session_id}", response_model=BrowserProcedureTeachingRead
)
async def change_session(
    session_id: UUID,
    data: BrowserProcedureTeachingChange,
    revision: Revision,
    ctx: Auth,
    service: BrowserProcedureTeachingSvc,
    response: Response,
) -> BrowserProcedureTeachingRead:
    return with_etag(response, await service.change(ctx, session_id, revision, data))


@router.post(
    "/browser-procedures/teachings/{session_id}/stop",
    response_model=BrowserProcedureTeachingRead,
)
async def stop_session(
    session_id: UUID,
    ctx: Auth,
    service: BrowserProcedureTeachingSvc,
    response: Response,
) -> BrowserProcedureTeachingRead:
    return with_etag(response, await service.stop(ctx, session_id))


@router.delete(
    "/browser-procedures/teachings/{session_id}",
    response_model=BrowserProcedureTeachingRead,
)
async def discard_session(
    session_id: UUID,
    ctx: Auth,
    service: BrowserProcedureTeachingSvc,
    response: Response,
) -> BrowserProcedureTeachingRead:
    return with_etag(response, await service.discard(ctx, session_id))


@router.post(
    "/browser-procedures/teachings/{session_id}/propose",
    response_model=BrowserProcedureTeachingRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def propose(
    session_id: UUID,
    data: BrowserProcedureTeachingPropose,
    revision: Revision,
    ctx: Auth,
    service: BrowserProcedureTeachingDraftSvc,
    response: Response,
) -> BrowserProcedureTeachingRead:
    return with_etag(response, await service.propose(ctx, session_id, revision, data))


@router.get("/browser-teaching-policy", response_model=BrowserProcedureTeachingPolicyRead)
async def read_policy(
    ctx: Auth, service: BrowserProcedureTeachingPolicySvc
) -> BrowserProcedureTeachingPolicyRead:
    return await service.get(ctx)


@router.put(
    "/browser-teaching-policy",
    response_model=BrowserProcedureTeachingPolicyRead,
    dependencies=[Depends(require(Perm.ORG_SETTINGS))],
)
async def update_policy(
    data: BrowserProcedureTeachingPolicyWrite,
    ctx: Auth,
    service: BrowserProcedureTeachingPolicySvc,
) -> BrowserProcedureTeachingPolicyRead:
    return await service.update(ctx, data)


@router.get(
    "/agents/{agent_id}/browser-teaching-preference",
    response_model=BrowserProcedureTeachingPreferenceRead,
)
async def read_preference(
    agent_id: UUID,
    ctx: Auth,
    service: BrowserProcedureTeachingPolicySvc,
) -> BrowserProcedureTeachingPreferenceRead:
    return await service.preference(ctx, agent_id)


@router.put(
    "/agents/{agent_id}/browser-teaching-preference",
    response_model=BrowserProcedureTeachingPreferenceRead,
)
async def update_preference(
    agent_id: UUID,
    data: BrowserProcedureTeachingPreferenceWrite,
    ctx: Auth,
    service: BrowserProcedureTeachingPolicySvc,
) -> BrowserProcedureTeachingPreferenceRead:
    return await service.update_preference(ctx, agent_id, data)
