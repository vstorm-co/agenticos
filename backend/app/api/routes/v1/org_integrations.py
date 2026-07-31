"""Org-level sync source (integration) management.

These endpoints manage sync sources at the organisation level: an integration
without a `collection_name` is a "template" that can later be cloned into one
or more knowledge bases.

Gated on `connections:manage` - the permission the catalog says governs
org-wide credentials - rather than a role-name list. This used to be
`RequireAdminPlus`, the one surface that checked role names, and it refused a
Builder the matrix promised `connections:manage` to.

The gate checks the caller's permission *in their active organization*; it
says nothing about which organization the row in the path belongs to. So the
per-source routes resolve the id through
:meth:`app.services.collection_access.CollectionAccessService.sync_source`
first - otherwise an admin of any organization could trigger, inspect or delete
another one's integration, and these rows hold encrypted credentials.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    Auth,
    CollectionAccessSvc,
    DBSession,
    SyncSourceSvc,
    require,
)
from app.core.permissions import Perm
from app.repositories import sync_log as sync_log_repo
from app.schemas.rag import RAGSyncLogItem, RAGSyncLogList, RAGSyncResponse
from app.schemas.sync_source import (
    ConnectorList,
    SyncSourceCreate,
    SyncSourceList,
    SyncSourceRead,
)

router = APIRouter()


@router.get(
    "",
    response_model=SyncSourceList,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def list_org_integrations(
    sync_source_svc: SyncSourceSvc,
    ctx: Auth,
) -> Any:
    """List all sync source integrations for the active organisation.

    Returns both unassigned (org-level) and KB-assigned sources.

    This is the only way to enumerate the *unassigned* ones - every other
    listing is scoped to a collection, and a source with no `collection_name`
    belongs to none - which is what the "Reusable integrations" section on
    `/kb` reads. It keeps the assigned rows in the response because they are
    the same organisation's, and a caller wanting the full picture has nowhere
    else to get it; the UI filters to what its own surface owns.
    """
    return await sync_source_svc.list_sources(organization_id=ctx.organization_id)


@router.get(
    "/connectors",
    response_model=ConnectorList,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def list_org_connectors(
    sync_source_svc: SyncSourceSvc,
) -> Any:
    """List available connector types (Google Drive, S3, …)."""
    return sync_source_svc.list_connectors()


@router.post(
    "",
    response_model=SyncSourceRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def create_org_integration(
    data: SyncSourceCreate,
    sync_source_svc: SyncSourceSvc,
    ctx: Auth,
) -> Any:
    """Create an org-level integration.

    Omit `collection_name` to keep it unassigned - it can be cloned
    into multiple knowledge bases later.  Pass a `collection_name` to
    immediately wire it to a specific KB collection.
    """
    return await sync_source_svc.create_source(data, organization_id=ctx.organization_id)


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def delete_org_integration(
    source_id: UUID,
    sync_source_svc: SyncSourceSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> None:
    """Delete an org integration by ID."""
    source = await access.sync_source(ctx, str(source_id))
    await sync_source_svc.delete_source(str(source.id))


@router.post(
    "/{source_id}/trigger",
    response_model=RAGSyncResponse,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def trigger_org_integration(
    source_id: UUID,
    sync_source_svc: SyncSourceSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> Any:
    """Manually trigger a sync run for an org integration."""
    source = await access.sync_source(ctx, str(source_id))
    sync_log = await sync_source_svc.trigger_sync(str(source.id))
    return RAGSyncResponse(
        id=str(sync_log.id),
        status="running",
        message=f"Sync triggered for integration '{source_id}'",
    )


@router.get(
    "/{source_id}/logs",
    response_model=RAGSyncLogList,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def list_org_integration_logs(
    source_id: UUID,
    db: DBSession,
    access: CollectionAccessSvc,
    ctx: Auth,
    limit: int = Query(20, ge=1, le=100),
) -> Any:
    """List sync run history for a specific org integration."""
    source = await access.sync_source(ctx, str(source_id))
    logs = await sync_log_repo.get_all(db, sync_source_id=source.id, limit=limit)
    items = [
        RAGSyncLogItem(
            id=str(log.id),
            source=log.source,
            collection_name=log.collection_name,
            status=log.status,
            mode=log.mode,
            total_files=log.total_files,
            ingested=log.ingested,
            updated=log.updated,
            skipped=log.skipped,
            failed=log.failed,
            error_message=log.error_message,
            started_at=log.started_at,
            completed_at=log.completed_at,
        )
        for log in logs
    ]
    return RAGSyncLogList(items=items, total=len(items))
