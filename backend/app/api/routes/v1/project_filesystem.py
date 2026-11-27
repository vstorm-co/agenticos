"""Machine-only filesystem gateway, scoped to one sandbox and its admitted run leases."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response

from app.api.deps import (
    ProjectFilesystemBindingSvc,
    ProjectFilesystemGatewaySvc,
    ProjectFilesystemToken,
)
from app.schemas.project_filesystem import FsRequest, FsResponse
from app.schemas.project_filesystem_authority import ProjectFilesystemBindingRead

router = APIRouter()


@router.get("/bindings/{binding_id}", response_model=ProjectFilesystemBindingRead)
async def binding_proof(
    binding_id: UUID,
    bindings: ProjectFilesystemBindingSvc,
    token: ProjectFilesystemToken,
    response: Response,
) -> Any:
    """Prove the exact session/tenant identity to the trusted sandbox supervisor."""
    response.headers["Cache-Control"] = "no-store"
    return await bindings.proof(binding_id, token)


@router.post(
    "/bindings/{binding_id}/fs", response_model=FsResponse, response_model_exclude_none=True
)
async def filesystem_operation(
    binding_id: UUID,
    request: FsRequest,
    gateway: ProjectFilesystemGatewaySvc,
    token: ProjectFilesystemToken,
    response: Response,
) -> Any:
    """Perform one bounded filesystem operation and commit it before acknowledging.

    The dedicated binding token grants no Project authority on its own. The
    immutable run directory in the path is reauthorized on every request.
    """
    response.headers["Cache-Control"] = "no-store"
    return await gateway.perform(binding_id, token, request)
