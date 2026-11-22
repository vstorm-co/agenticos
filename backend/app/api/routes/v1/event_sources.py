"""Reusable source configuration and live capture; no sample operation executes a target."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.deps import Auth, EventSourceSampleSvc, EventSourceSvc, limit_workflow_webhook, require
from app.api.public_api import PUBLIC
from app.core.permissions import Perm
from app.schemas.event_source import (
    EventSourceCreate,
    EventSourceCreated,
    EventSourceList,
    EventSourceRead,
    EventSourceUpdate,
    SourceCapture,
    SourceCredentials,
    SourceListening,
    SourceUsageList,
)
from app.services.workflow_execution.resume import read_workflow_body

router = APIRouter(dependencies=[PUBLIC])
public_router = APIRouter()


@router.get(
    "", response_model=EventSourceList, dependencies=[Depends(require(Perm.EVENT_SOURCES_VIEW))]
)
async def list_sources(
    ctx: Auth,
    service: EventSourceSvc,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """List a page of sources visible to the caller."""
    return await service.list(ctx, skip=skip, limit=limit)


@router.post(
    "",
    response_model=EventSourceCreated,
    status_code=201,
    dependencies=[Depends(require(Perm.EVENT_SOURCES_EDIT))],
)
async def create_source(data: EventSourceCreate, ctx: Auth, service: EventSourceSvc) -> Any:
    return await service.create(ctx, data)


@router.get("/{source_id}", response_model=EventSourceRead)
async def read_source(source_id: UUID, ctx: Auth, service: EventSourceSvc) -> Any:
    return await service.read(ctx, await service.get(ctx, source_id))


@router.patch("/{source_id}", response_model=EventSourceRead)
async def update_source(
    source_id: UUID, data: EventSourceUpdate, ctx: Auth, service: EventSourceSvc
) -> Any:
    return await service.update(ctx, source_id, data)


@router.delete("/{source_id}", response_model=None, status_code=204)
async def delete_source(source_id: UUID, ctx: Auth, service: EventSourceSvc) -> Any:
    await service.delete(ctx, source_id)


@router.post("/{source_id}/credentials", response_model=None, status_code=204)
async def replace_credentials(
    source_id: UUID, data: SourceCredentials, ctx: Auth, service: EventSourceSvc
) -> Any:
    await service.replace_credentials(ctx, source_id, data)


@router.get("/{source_id}/usage", response_model=SourceUsageList)
async def source_usage(source_id: UUID, ctx: Auth, service: EventSourceSvc) -> Any:
    return await service.usage(ctx, source_id)


@router.post("/{source_id}/listen", response_model=SourceListening)
async def listen(source_id: UUID, ctx: Auth, service: EventSourceSampleSvc) -> Any:
    """Listen for the next delivery using this source's use permission; no target is required."""
    return await service.listen(ctx, source_id)


@router.get("/{source_id}/listen/{token}", response_model=SourceCapture)
async def caught(source_id: UUID, token: str, ctx: Auth, service: EventSourceSampleSvc) -> Any:
    """Read your listener's sample while you can still use the source in this organization."""
    return await service.caught(ctx, source_id, token)


@public_router.post(
    "/sources/{source_id}",
    dependencies=[Depends(limit_workflow_webhook)],
    response_model=None,
    status_code=202,
    responses={200: {"description": "Linear delivery accepted"}},
)
async def receive(
    source_id: UUID, request: Request, service: EventSourceSvc, samples: EventSourceSampleSvc
) -> Any:
    """Authenticate POST JSON once and acknowledge durable receipt, never wait for an agent."""
    body = await read_workflow_body(request.stream())
    received_at = datetime.now(UTC)
    source, receipt, _ = await service.receive(source_id, body=body, headers=request.headers)
    assert receipt.body is not None
    samples.capture_after_commit(
        source.id,
        body=receipt.body,
        delivery_id=receipt.external_id or str(receipt.id),
        received_at=received_at,
    )
    return Response(status_code=200 if source.provider == "linear" else 202)
