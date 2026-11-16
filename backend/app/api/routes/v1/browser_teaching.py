"""Owner-scoped capture metadata and explicit review; no client append or replay endpoint."""

import re
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.api.deps import (
    Auth,
    BrowserTeachingDraftSvc,
    BrowserTeachingPolicySvc,
    BrowserTeachingSvc,
    no_store_response,
    require,
)
from app.core.exceptions import BadRequestError
from app.core.permissions import Perm
from app.schemas.browser_teaching import (
    TeachingChange,
    TeachingList,
    TeachingPolicyRead,
    TeachingPolicyWrite,
    TeachingPreferenceRead,
    TeachingPreferenceWrite,
    TeachingPropose,
    TeachingRead,
    TeachingStart,
)

router = APIRouter(dependencies=[Depends(no_store_response)])


def _revision(value: Annotated[str, Header(alias="If-Match", max_length=32)]) -> int:
    if re.fullmatch(r'(?:[1-9][0-9]{0,9}|"[1-9][0-9]{0,9}")', value) is None:
        raise BadRequestError(message="Provide the current teaching revision in If-Match")
    return int(value.strip('"'))


Revision = Annotated[int, Depends(_revision)]


def _read(response: Response, data: TeachingRead) -> TeachingRead:
    response.headers["ETag"] = f'"{data.revision}"'
    return data


@router.post(
    "/browser-teachings",
    response_model=TeachingRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.SKILLS_EDIT))],
)
async def start_new(
    data: TeachingStart, ctx: Auth, service: BrowserTeachingSvc, response: Response
) -> TeachingRead:
    return _read(response, await service.start(ctx, data))


@router.post(
    "/skills/{skill_id}/browser-teachings",
    response_model=TeachingRead,
    status_code=status.HTTP_201_CREATED,
)
async def start_for_skill(
    skill_id: UUID, data: TeachingStart, ctx: Auth, service: BrowserTeachingSvc, response: Response
) -> TeachingRead:
    return _read(response, await service.start(ctx, data, skill_id=skill_id))


@router.get("/browser-teachings", response_model=TeachingList)
async def list_sessions(
    ctx: Auth,
    service: BrowserTeachingSvc,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> Any:
    """Find the current personal owner's captures, newest first in the active organization.

    A page carries only closed summary metadata. Opening a capture or making a
    decision still requires its per-ID owner read and existing effect authority.
    Cursors are opaque and audience-bound; an invalid cursor returns
    BAD_REQUEST with details.reason_code=invalid_cursor. Start again without it.
    """
    return await service.list(ctx, limit=limit, cursor=cursor)


@router.get("/browser-teachings/{session_id}", response_model=TeachingRead)
async def read_session(
    session_id: UUID, ctx: Auth, service: BrowserTeachingSvc, response: Response
) -> TeachingRead:
    return _read(response, await service.get(ctx, session_id))


@router.patch("/browser-teachings/{session_id}", response_model=TeachingRead)
async def change_session(
    session_id: UUID,
    data: TeachingChange,
    revision: Revision,
    ctx: Auth,
    service: BrowserTeachingSvc,
    response: Response,
) -> TeachingRead:
    return _read(response, await service.change(ctx, session_id, revision, data))


@router.post("/browser-teachings/{session_id}/stop", response_model=TeachingRead)
async def stop_session(
    session_id: UUID, ctx: Auth, service: BrowserTeachingSvc, response: Response
) -> TeachingRead:
    return _read(response, await service.stop(ctx, session_id))


@router.delete("/browser-teachings/{session_id}", response_model=TeachingRead)
async def discard_session(
    session_id: UUID, ctx: Auth, service: BrowserTeachingSvc, response: Response
) -> TeachingRead:
    return _read(response, await service.discard(ctx, session_id))


@router.post(
    "/browser-teachings/{session_id}/propose",
    response_model=TeachingRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def propose(
    session_id: UUID,
    data: TeachingPropose,
    revision: Revision,
    ctx: Auth,
    service: BrowserTeachingDraftSvc,
    response: Response,
) -> TeachingRead:
    return _read(response, await service.propose(ctx, session_id, revision, data))


@router.get("/browser-teaching-policy", response_model=TeachingPolicyRead)
async def read_policy(ctx: Auth, service: BrowserTeachingPolicySvc) -> TeachingPolicyRead:
    return await service.get(ctx)


@router.put(
    "/browser-teaching-policy",
    response_model=TeachingPolicyRead,
    dependencies=[Depends(require(Perm.ORG_SETTINGS))],
)
async def update_policy(
    data: TeachingPolicyWrite, ctx: Auth, service: BrowserTeachingPolicySvc
) -> TeachingPolicyRead:
    return await service.update(ctx, data)


@router.get("/agents/{agent_id}/browser-teaching-preference", response_model=TeachingPreferenceRead)
async def read_preference(
    agent_id: UUID, ctx: Auth, service: BrowserTeachingPolicySvc
) -> TeachingPreferenceRead:
    return await service.preference(ctx, agent_id)


@router.put("/agents/{agent_id}/browser-teaching-preference", response_model=TeachingPreferenceRead)
async def update_preference(
    agent_id: UUID, data: TeachingPreferenceWrite, ctx: Auth, service: BrowserTeachingPolicySvc
) -> TeachingPreferenceRead:
    return await service.update_preference(ctx, agent_id, data)
