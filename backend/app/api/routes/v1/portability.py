"""Private resource transfer tickets, streamed uploads and reviewed imports."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import Auth, PortableTransferSvc, require
from app.core.permissions import Perm
from app.schemas.portability_operation import (
    BundleApplyCreate,
    BundleExportStart,
    BundleUploadStart,
    PortabilityOperationRead,
)

router = APIRouter(prefix="/portability", tags=["Portability"])


@router.post(
    "/exports",
    response_model=PortabilityOperationRead,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require(Perm.AGENTS_EDIT))],
)
async def start_export(data: BundleExportStart, service: PortableTransferSvc, ctx: Auth) -> Any:
    """Queue a ZIP export. The same request ID replays the same transfer."""
    return await service.start_export(ctx, data)


@router.post(
    "/uploads",
    response_model=PortabilityOperationRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.AGENTS_EDIT))],
)
async def start_upload(data: BundleUploadStart, service: PortableTransferSvc, ctx: Auth) -> Any:
    """Reserve an expiring, owner-scoped upload before sending its bytes."""
    return await service.start_upload(ctx, data)


@router.put("/{operation_id}/upload", response_model=PortabilityOperationRead)
async def upload_bundle(
    operation_id: UUID, request: Request, service: PortableTransferSvc, ctx: Auth
) -> Any:
    """Stream raw ZIP bytes; actual bytes must equal the ticket's declared size."""
    return await service.upload(ctx, operation_id, request.stream())


@router.get("/{operation_id}", response_model=PortabilityOperationRead)
async def get_transfer(operation_id: UUID, service: PortableTransferSvc, ctx: Auth) -> Any:
    """Read progress or refresh destination availability for an uploaded bundle."""
    return await service.get(ctx, operation_id)


@router.post(
    "/{operation_id}/apply",
    response_model=PortabilityOperationRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def apply_bundle(
    operation_id: UUID, data: BundleApplyCreate, service: PortableTransferSvc, ctx: Auth
) -> Any:
    """Queue the reviewed import; no resource is published, run or indexed."""
    return await service.apply(ctx, operation_id, data)


@router.get("/{operation_id}/download", response_class=StreamingResponse)
async def download_bundle(operation_id: UUID, service: PortableTransferSvc, ctx: Auth) -> Any:
    """Recheck access and stream an expiring private ZIP, without exposing storage keys."""
    return StreamingResponse(
        await service.download(ctx, operation_id),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="agenticos-{operation_id}.zip"',
            "Cache-Control": "no-store",
        },
    )
