"""Knowledge Base routes - CRUD + per-KB document upload + sync sources.

Document upload and sync-source management are wired here (rather than under
`/rag`) so non-admin owners can manage their own KB without needing the
app-admin role required by the bulk `/rag` endpoints.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import (
    Auth,
    CollectionAccessSvc,
    DBSession,
    KnowledgeBaseSvc,
    RAGDocumentSvc,
    SyncSourceSvc,
    VectorStoreSvc,
    require,
)
from app.core.exceptions import NotFoundError
from app.core.permissions import Perm
from app.db.models.knowledge_base import KnowledgeBase
from app.repositories import sync_log as sync_log_repo
from app.repositories.rag_document import CollectionCounts
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseList,
    KnowledgeBaseRead,
    KnowledgeBaseUpdate,
)
from app.schemas.rag import (
    RAGIngestResponse,
    RAGParsedContent,
    RAGSyncLogItem,
    RAGSyncLogList,
    RAGSyncResponse,
    RAGTrackedDocumentList,
)
from app.schemas.sync_source import (
    ConnectorList,
    SyncSourceClone,
    SyncSourceCreate,
    SyncSourceList,
    SyncSourceRead,
)
from app.services.ingestion_config import parse_override

router = APIRouter()


@router.get(
    "", response_model=KnowledgeBaseList, dependencies=[Depends(require(Perm.COLLECTIONS_VIEW))]
)
async def list_knowledge_bases(
    service: KnowledgeBaseSvc,
    ctx: Auth,
) -> Any:
    """List the Knowledge Bases this caller may read in the active organization.

    Carries each collection's document and chunk counts, which the single-row
    responses do not. A picker choosing what an agent may search is choosing
    between collections, and a name alone does not distinguish the one with four
    hundred documents in it from the one somebody made and never filled.
    """
    items = await service.list_accessible(ctx)
    counts = await service.counts_for(items)
    return KnowledgeBaseList(
        items=[_read_with_counts(kb, counts.get(kb.collection_name)) for kb in items],
        total=len(items),
    )


def _read_with_counts(kb: KnowledgeBase, counts: CollectionCounts | None) -> KnowledgeBaseRead:
    """A collection as the listing shows it, contents included.

    `counts` is `None` for a collection nothing has been written to - the group
    query has no row to return for it - and the zeros that stands for are the
    schema's own defaults.
    """
    read = KnowledgeBaseRead.model_validate(kb)
    if counts is None:
        return read
    return read.model_copy(
        update={
            "document_count": counts.documents,
            "indexed_count": counts.indexed,
            "chunk_count": counts.chunks,
        }
    )


@router.post(
    "",
    response_model=KnowledgeBaseRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.COLLECTIONS_EDIT))],
)
async def create_knowledge_base(
    data: KnowledgeBaseCreate,
    service: KnowledgeBaseSvc,
    ctx: Auth,
) -> Any:
    """Create a new Knowledge Base.

    - `personal` scope: visible only to you
    - `org` scope: owned by you, private until shared or made org-visible
    - `app` scope: visible to all users (app admin only)

    `ingestion_config` decides how this collection's documents will be parsed,
    chunked and described; omit it for this deployment's defaults. The embedding
    model is recorded from the deployment and is not settable - a collection's
    vectors are only comparable with themselves.
    """
    return await service.create(data, ctx=ctx)


# Per-resource routes carry no `require()` gate on purpose: a role gate cannot
# see the grants on a row, so it would refuse a Viewer holding an explicit
# `edit` grant before the service's `resolve_access` ever widened their reach.
# The service decides per row; the collection routes above keep the role gate.


@router.get("/{kb_id}", response_model=KnowledgeBaseRead)
async def get_knowledge_base(
    kb_id: UUID,
    service: KnowledgeBaseSvc,
    ctx: Auth,
) -> Any:
    """Get a Knowledge Base by ID."""
    return await service.get(kb_id, ctx=ctx)


@router.patch("/{kb_id}", response_model=KnowledgeBaseRead)
async def update_knowledge_base(
    kb_id: UUID,
    data: KnowledgeBaseUpdate,
    service: KnowledgeBaseSvc,
    ctx: Auth,
) -> Any:
    """Update the name, description or ingestion configuration of a Knowledge Base.

    A new `ingestion_config` applies to documents ingested from now on.
    Nothing already indexed is re-parsed, and the embedding model cannot be
    changed here at all.
    """
    return await service.update(kb_id, data, ctx=ctx)


@router.delete(
    "/{kb_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_knowledge_base(
    kb_id: UUID,
    service: KnowledgeBaseSvc,
    ctx: Auth,
) -> None:
    """Delete a Knowledge Base. Default KBs cannot be deleted."""
    await service.delete(kb_id, ctx=ctx)


@router.get("/{kb_id}/documents", response_model=RAGTrackedDocumentList)
async def list_kb_documents(
    kb_id: UUID,
    service: KnowledgeBaseSvc,
    rag_doc_service: RAGDocumentSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """List documents ingested into a Knowledge Base."""
    await service.get(kb_id, ctx=ctx)
    return await rag_doc_service.list_for_kb(kb_id=kb_id, skip=skip, limit=limit)


@router.post(
    "/{kb_id}/documents",
    response_model=RAGIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_kb_document(
    kb_id: UUID,
    service: KnowledgeBaseSvc,
    rag_doc_service: RAGDocumentSvc,
    vector_store: VectorStoreSvc,
    ctx: Auth,
    file: UploadFile = File(...),
    replace: bool = Query(False),
    ingestion: str | None = Form(
        default=None,
        description=(
            "JSON object departing from the collection's ingestion configuration "
            'for this file only, e.g. {"pdf_parser": "llamaparse"}. Omitted '
            "keys keep the collection's setting. Recorded on the document."
        ),
    ),
) -> Any:
    """Upload a file into the KB's underlying vector collection.

    Auth is per-KB rather than the app-admin role the bulk
    `/rag/{collection}/documents` endpoint demands, so a workspace user can
    manage their own KB without elevation - but it is *write* access the
    service resolves, not read: `collections:edit` reaching this base, or an
    explicit edit grant on it. Overriding how this one file is parsed needs no
    permission beyond that: it changes nothing outside the document being
    added.
    """
    kb = await service.get_for_write(kb_id, ctx=ctx)
    data = await file.read()
    return await rag_doc_service.dispatch_upload(
        ctx=ctx,
        collection=kb,
        file_data=data,
        filename=file.filename or "unknown",
        replace=replace,
        vector_store=vector_store,
        override=parse_override(ingestion),
        organization_id=ctx.organization_id,
        knowledge_base_id=kb.id,
    )


@router.get("/{kb_id}/documents/{doc_id}/download", response_model=None)
async def download_kb_document(
    kb_id: UUID,
    doc_id: UUID,
    service: KnowledgeBaseSvc,
    rag_doc_svc: RAGDocumentSvc,
    ctx: Auth,
) -> FileResponse:
    """Download (or open inline) the original file for a KB document."""
    kb = await service.get(kb_id, ctx=ctx)
    doc = await rag_doc_svc.get_document(str(doc_id))
    if doc.collection_name != kb.collection_name:
        raise NotFoundError(
            message="Document not found in this knowledge base",
            details={"kb_id": str(kb_id), "doc_id": str(doc_id)},
        )
    file_path, filename, mime_type = await rag_doc_svc.get_download_info(str(doc_id))
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=mime_type,
        # The BFF forwards this rather than inventing one, which is why it is here:
        # a stored document does not change, and re-downloading it every time the
        # viewer is opened is a round trip for bytes the browser already has.
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/{kb_id}/documents/{doc_id}/parsed", response_model=RAGParsedContent)
async def get_kb_document_parsed(
    kb_id: UUID,
    doc_id: UUID,
    service: KnowledgeBaseSvc,
    rag_doc_svc: RAGDocumentSvc,
    vector_store: VectorStoreSvc,
    ctx: Auth,
) -> Any:
    """How a KB document parsed: the indexed chunks, grouped back into pages.

    The counterpart of `download` above - original bytes there, what the
    parser made of them here - so the two can be compared side by side. A
    document still processing, or one whose ingestion failed, is a 404: there
    is no parse to show yet.
    """
    kb = await service.get(kb_id, ctx=ctx)
    doc = await rag_doc_svc.get_document(str(doc_id))
    if doc.collection_name != kb.collection_name:
        raise NotFoundError(
            message="Document not found in this knowledge base",
            details={"kb_id": str(kb_id), "doc_id": str(doc_id)},
        )
    return await rag_doc_svc.get_parsed_content(str(doc_id), vector_store)


@router.delete(
    "/{kb_id}/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_kb_document(
    kb_id: UUID,
    doc_id: UUID,
    service: KnowledgeBaseSvc,
    rag_doc_service: RAGDocumentSvc,
    ctx: Auth,
) -> None:
    """Remove a document from the KB (cascades to vectors + file storage).

    Verifies the doc actually belongs to this KB's collection - without that
    check a KB owner could pass any doc_id and remove docs from KBs they
    don't own.
    """
    kb = await service.get_for_write(kb_id, ctx=ctx)
    doc = await rag_doc_service.get_document(str(doc_id))
    if doc.collection_name != kb.collection_name:
        raise NotFoundError(
            message="Document not found in this knowledge base",
            details={"kb_id": str(kb_id), "doc_id": str(doc_id)},
        )
    await rag_doc_service.delete_document(str(doc_id))


# These mirror /rag/sync/sources but with per-KB auth (a personal KB owner
# can wire up a Google Drive folder without admin role) and automatically
# pin the source to `kb.collection_name` so the user can't accidentally
# point a sync at a different collection.


@router.get("/{kb_id}/sync-sources", response_model=SyncSourceList)
async def list_kb_sync_sources(
    kb_id: UUID,
    service: KnowledgeBaseSvc,
    sync_source_svc: SyncSourceSvc,
    ctx: Auth,
) -> Any:
    """List sync sources feeding this KB's collection (org-scoped)."""
    kb = await service.get(kb_id, ctx=ctx)
    return await sync_source_svc.list_sources(
        organization_id=ctx.organization_id,
        collection_name=kb.collection_name,
    )


@router.get("/{kb_id}/sync-sources/org-integrations", response_model=SyncSourceList)
async def list_org_integrations_for_kb(
    kb_id: UUID,
    service: KnowledgeBaseSvc,
    sync_source_svc: SyncSourceSvc,
    ctx: Auth,
) -> Any:
    """List org integrations that are NOT yet assigned to this KB.

    Used by the wizard's 'pick existing' step so the user can clone an
    existing integration's credentials into this knowledge base.
    """
    kb = await service.get(kb_id, ctx=ctx)
    all_org = await sync_source_svc.list_sources(organization_id=ctx.organization_id)
    others = [s for s in all_org.items if s.collection_name != kb.collection_name]
    return SyncSourceList(items=others, total=len(others))


@router.get("/{kb_id}/sync-sources/connectors", response_model=ConnectorList)
async def list_kb_connectors(
    kb_id: UUID,
    service: KnowledgeBaseSvc,
    sync_source_svc: SyncSourceSvc,
    ctx: Auth,
) -> Any:
    """List available connector types (Google Drive, S3, …) for this KB."""
    await service.get(kb_id, ctx=ctx)
    return sync_source_svc.list_connectors()


@router.post(
    "/{kb_id}/sync-sources",
    response_model=SyncSourceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_kb_sync_source(
    kb_id: UUID,
    data: SyncSourceCreate,
    service: KnowledgeBaseSvc,
    sync_source_svc: SyncSourceSvc,
    ctx: Auth,
) -> Any:
    """Wire up a sync source (Google Drive, S3, …) feeding this KB.

    The `collection_name` field on the request body is overridden with the
    KB's own collection - clients should not need to know that detail.
    """
    kb = await service.get_for_write(kb_id, ctx=ctx)
    payload = data.model_copy(update={"collection_name": kb.collection_name})
    return await sync_source_svc.create_source(payload, organization_id=ctx.organization_id)


@router.post(
    "/{kb_id}/sync-sources/{source_id}/clone",
    response_model=SyncSourceRead,
    status_code=status.HTTP_201_CREATED,
)
async def clone_kb_sync_source(
    kb_id: UUID,
    source_id: UUID,
    data: SyncSourceClone,
    service: KnowledgeBaseSvc,
    sync_source_svc: SyncSourceSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> Any:
    """Clone an existing org integration into this KB.

    Decrypts credentials from the source and re-encrypts them for the clone,
    pinning it to this KB's collection_name. The clone is independent.

    The source is resolved inside the caller's organization first. Without that
    the destination was checked and the *origin* was not: any id would do, and
    cloning re-encrypts the credentials it finds - so a caller could point
    another tenant's Google Drive at their own collection and sync it.
    """
    kb = await service.get_for_write(kb_id, ctx=ctx)
    source = await access.sync_source(ctx, str(source_id))
    clone_data = data.model_copy(update={"collection_name": kb.collection_name})
    return await sync_source_svc.clone_source(
        str(source.id), clone_data, organization_id=ctx.organization_id
    )


@router.post(
    "/{kb_id}/sync-sources/{source_id}/trigger",
    response_model=RAGSyncResponse,
)
async def trigger_kb_sync_source(
    kb_id: UUID,
    source_id: UUID,
    service: KnowledgeBaseSvc,
    sync_source_svc: SyncSourceSvc,
    ctx: Auth,
) -> Any:
    """Manually trigger a sync run for one of this KB's sources."""
    kb = await service.get_for_write(kb_id, ctx=ctx)
    source = await sync_source_svc.get_source(str(source_id))
    if source.collection_name != kb.collection_name:
        raise NotFoundError(
            message="Sync source not found in this knowledge base",
            details={"kb_id": str(kb_id), "source_id": str(source_id)},
        )
    sync_log = await sync_source_svc.trigger_sync(str(source_id))
    return RAGSyncResponse(
        id=str(sync_log.id),
        status="running",
        message=f"Sync triggered for source '{source_id}'",
    )


@router.get("/{kb_id}/sync-sources/{source_id}/logs", response_model=RAGSyncLogList)
async def list_kb_sync_source_logs(
    kb_id: UUID,
    source_id: UUID,
    service: KnowledgeBaseSvc,
    db: DBSession,
    ctx: Auth,
    limit: int = Query(20, ge=1, le=100),
) -> Any:
    """List sync run history for a specific KB sync source."""
    kb = await service.get(kb_id, ctx=ctx)
    logs = await sync_log_repo.get_all(db, sync_source_id=source_id, limit=limit)
    # Verify source belongs to this KB's collection (security: don't leak other KBs' logs).
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
        if log.collection_name == kb.collection_name
    ]
    return RAGSyncLogList(items=items, total=len(items))


@router.delete(
    "/{kb_id}/sync-sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_kb_sync_source(
    kb_id: UUID,
    source_id: UUID,
    service: KnowledgeBaseSvc,
    sync_source_svc: SyncSourceSvc,
    ctx: Auth,
) -> None:
    """Remove a sync source from this KB."""
    kb = await service.get_for_write(kb_id, ctx=ctx)
    source = await sync_source_svc.get_source(str(source_id))
    if source.collection_name != kb.collection_name:
        raise NotFoundError(
            message="Sync source not found in this knowledge base",
            details={"kb_id": str(kb_id), "source_id": str(source_id)},
        )
    await sync_source_svc.delete_source(str(source_id))
