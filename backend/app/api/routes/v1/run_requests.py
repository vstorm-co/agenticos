"""Polling an asynchronous agent run (#2219).

`POST /agents/{id}/run` with `Prefer: respond-async` answers `202` and a
`Location` naming one of these. Gated like the run itself, for a key, on what
it was issued for; whose request it is, is the service's to decide.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import ApiRunSvc, Auth, key_needs
from app.api.public_api import PUBLIC
from app.core.permissions import Perm
from app.schemas.agent import RunRequestRead

router = APIRouter(dependencies=[PUBLIC])


@router.get(
    "/run-requests/{request_id}",
    response_model=RunRequestRead,
    dependencies=[Depends(key_needs(Perm.AGENTS_RUN))],
)
async def get_run_request(request_id: UUID, service: ApiRunSvc, ctx: Auth) -> Any:
    """Where a queued run is, and what it answered once it has finished.

    Only the person - or a key of the person - who asked can read it; anyone
    else's answers `404`.
    """
    return await service.get(ctx, request_id)
