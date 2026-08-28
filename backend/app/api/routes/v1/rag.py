"""RAG API routes - collection management, search, document upload, sync.

Routes are HTTP plumbing only. Business logic, file I/O and task dispatch all
live in their respective services. Domain exceptions raised by services are
mapped to HTTP responses by the global exception handlers in
`app.api.exception_handlers`; routes do not catch and re-wrap them.

Two things every route here does before it touches anything:

*The gate.* Reading requires `collections:view`, writing `collections:edit`
- the same permissions `/kb` is gated on, because it is the same resource at a
different address. These routes used to require the *platform admin* role, which
looked strict and was not: it kept ordinary members out of RAG entirely while
letting any platform admin read every tenant's collections, because the role says
nothing about which organization is being asked about.

*The resolution.* A collection name in a URL is a string; the
`knowledge_bases` row behind it is the thing that has an owner. Every route
resolves the name through :class:`app.services.collection_access.CollectionAccessService`
and works with what came back, so a name belonging to another organization is
indistinguishable from one that was never created.

`GET /supported-formats` and `GET /sync/connectors` are the exceptions, and
deliberately: they describe how this deployment is configured - which parsers and
connectors exist - and have no tenant dimension to scope to.

There used to be a third, `GET /status/stream`: an SSE feed of every ingestion
event in the deployment, with no authentication and no organization in its
payload. It is gone rather than fixed, and anything replacing it needs all three
of the pieces it never had - a tenant on each event (published by
`app.worker.tasks.rag_tasks`, which does not put one there), an authentication
scheme a browser `EventSource` can actually use, since it cannot send an
`Authorization` header, and a subscription filtered by that tenant. The /kb
page already reports ingestion status by polling the org-scoped document
listing, which is why the stream was not worth rebuilding.
"""

import contextlib
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import (
    Auth,
    CollectionAccessSvc,
    CurrentAppAdmin,
    IngestionSvc,
    KnowledgeBaseSvc,
    RAGDocumentSvc,
    RAGSyncSvc,
    RetrievalSvc,
    SyncSourceSvc,
    VectorStoreSvc,
    require,
)
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import Perm
from app.schemas.rag import (
    EmbeddingModelsResponse,
    RAGCollectionInfo,
    RAGCollectionList,
    RAGDocumentList,
    RAGIngestResponse,
    RAGMessageResponse,
    RAGRetryResponse,
    RAGSearchRequest,
    RAGSearchResponse,
    RAGSearchResult,
    RAGSyncLogList,
    RAGSyncRequest,
    RAGSyncResponse,
    RAGTrackedDocumentList,
    SupportedFormatsResponse,
)
from app.schemas.sync_source import (
    ConnectorList,
    SyncSourceClone,
    SyncSourceCreate,
    SyncSourceList,
    SyncSourceRead,
    SyncSourceUpdate,
)
from app.services.ingestion_config import PdfParserName, parse_override
from app.services.rag import embedding_providers
from app.services.rag.config import get_supported_formats

router = APIRouter()


@router.get("/embedding-models", response_model=EmbeddingModelsResponse)
async def list_embedding_models() -> Any:
    """Which providers this build can embed through, and the models each serves.

    Deployment description, like `/supported-formats`: the list feeds the
    create-collection form and the one that moves an existing collection to
    another provider, and hardcoding it in the client is how the form and the
    build drift apart. The defaults are named so the form can preselect what an
    untouched deployment would use.
    """
    return {
        "default": settings.EMBEDDING_MODEL,
        "default_provider": embedding_providers.deployment_provider().provider,
        "providers": [
            {
                "provider": entry.provider,
                "name": entry.name,
                "models": [{"model": model.model, "dim": model.dim} for model in entry.models],
                "deployment_key": entry.deployment_key,
            }
            for entry in embedding_providers.providers()
        ],
    }


@router.get("/supported-formats", response_model=SupportedFormatsResponse)
async def get_supported_formats_endpoint(
    parser: PdfParserName = Query(
        default=PdfParserName.PYMUPDF,
        description="Parser to answer for.",
    ),
) -> Any:
    """Return the file formats a parser reads.

    Which formats an upload form may offer follows the *collection's*
    `ingestion_config.pdf_parser`, so the caller names the parser. This used
    to answer for a single installation-wide `PDF_PARSER`, which meant a
    collection set to LlamaParse advertised only what PyMuPDF reads.
    """
    return {"parser": parser.value, "formats": sorted(get_supported_formats(parser.value))}


@router.get(
    "/collections",
    response_model=RAGCollectionList,
    dependencies=[Depends(require(Perm.COLLECTIONS_VIEW))],
)
async def list_collections(access: CollectionAccessSvc, ctx: Auth) -> Any:
    """List collections derived from Knowledge Base records.

    Single source of truth = KnowledgeBase rows, so /rag and /kb stay
    consistent: a freshly-created KB (whose vector table only materializes
    after the first document is ingested) still appears here, and dropping a
    collection here removes the KB too.
    """
    return RAGCollectionList(items=await access.readable_names(ctx))


@router.post(
    "/collections/{name}",
    status_code=status.HTTP_201_CREATED,
    response_model=RAGMessageResponse,
    dependencies=[Depends(require(Perm.COLLECTIONS_EDIT))],
)
async def create_collection(
    name: str,
    vector_store: VectorStoreSvc,
    kb_svc: KnowledgeBaseSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> Any:
    """Create and initialize a new collection.

    Also creates a matching KnowledgeBase row (idempotent) so the collection
    shows up on /kb as well as /rag. A name another organization already holds
    is refused rather than quietly aliased onto their vector table.
    """
    await access.claim(ctx, name)
    await vector_store.create_collection(name)
    await kb_svc.create_for_rag_collection(
        name, user_id=ctx.subject_id, organization_id=ctx.organization_id
    )
    return RAGMessageResponse(message=f"Collection '{name}' created successfully.")


@router.delete(
    "/collections/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require(Perm.COLLECTIONS_EDIT))],
)
async def drop_collection(
    name: str,
    vector_store: VectorStoreSvc,
    rag_doc_svc: RAGDocumentSvc,
    kb_svc: KnowledgeBaseSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> None:
    """Drop a collection - vectors, SQL document records, and the KB row.

    A name no knowledge base in the caller's reach owns is a 404. It used to be
    204 for absolutely anything, which is two problems in one answer: a
    destructive endpoint that reports success for a name it never found cannot
    be used to confirm a deletion, and that 204 was also what another tenant's
    collection returned.

    The vector table may not exist yet for a zero-document KB, so the
    vector-store drop is best-effort - but only against the database. It used to
    suppress `Exception`, which now also covers the store *refusing* the name:
    the drop would be skipped, the row and the document records deleted anyway,
    and the table left behind with nobody left who can name it. `SQLAlchemyError`
    is the "no such table" case this was written for; a `BadRequestError` is the
    store saying it will not touch that name, and the caller has to hear it.
    """
    collection = await access.writable(ctx, name)
    with contextlib.suppress(SQLAlchemyError):
        await vector_store.delete_collection(collection.collection_name)
    await rag_doc_svc.delete_by_collection(collection.collection_name)
    await kb_svc.delete_for_rag_collection(collection)


@router.get(
    "/collections/{name}/info",
    response_model=RAGCollectionInfo,
    dependencies=[Depends(require(Perm.COLLECTIONS_VIEW))],
)
async def get_collection_info(
    name: str,
    vector_store: VectorStoreSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> Any:
    """Retrieve stats for a specific collection."""
    collection = await access.readable(ctx, name)
    return await vector_store.get_collection_info(collection.collection_name)


@router.get(
    "/collections/{name}/documents",
    response_model=RAGDocumentList,
    dependencies=[Depends(require(Perm.COLLECTIONS_VIEW))],
)
async def list_documents(
    name: str,
    vector_store: VectorStoreSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> Any:
    """List all documents in a specific collection."""
    collection = await access.readable(ctx, name)
    return await vector_store.get_document_list(collection.collection_name)


@router.post(
    "/search",
    response_model=RAGSearchResponse,
    dependencies=[Depends(require(Perm.COLLECTIONS_VIEW))],
)
async def search_documents(
    request: RAGSearchRequest,
    retrieval_service: RetrievalSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> Any:
    """Search for relevant document chunks. Supports multi-collection search.

    Every collection named is resolved before the first vector is read, and one
    the caller cannot reach refuses the whole search rather than being dropped
    from it - see `CollectionAccessService.readable_all`.
    """
    names = request.collection_names or [request.collection_name]
    collections = [kb.collection_name for kb in await access.readable_all(ctx, names)]
    if len(collections) > 1:
        results = await retrieval_service.retrieve_multi(
            query=request.query,
            collection_names=collections,
            limit=request.limit,
            min_score=request.min_score,
        )
    else:
        results = await retrieval_service.retrieve(
            query=request.query,
            collection_name=collections[0],
            limit=request.limit,
            min_score=request.min_score,
            filter=request.filter or "",
        )
    api_results = [RAGSearchResult(**hit.model_dump()) for hit in results]
    return RAGSearchResponse(results=api_results)


@router.delete(
    "/collections/{name}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require(Perm.COLLECTIONS_EDIT))],
)
async def delete_document(
    name: str,
    document_id: str,
    ingestion_service: IngestionSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> None:
    """Delete a specific document by its ID from a collection."""
    collection = await access.writable(ctx, name)
    success = await ingestion_service.remove_document(collection.collection_name, document_id)
    if not success:
        raise NotFoundError(
            message="Document not found",
            details={"collection": name, "document_id": document_id},
        )


@router.post(
    "/collections/{name}/ingest",
    response_model=RAGIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require(Perm.COLLECTIONS_EDIT))],
)
async def ingest_file(
    name: str,
    rag_doc_svc: RAGDocumentSvc,
    vector_store: VectorStoreSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
    file: UploadFile = File(...),
    replace: bool = Query(False),
    ingestion: str | None = Form(
        default=None,
        description=(
            "JSON object departing from the collection's ingestion configuration "
            "for this file only. Omitted keys keep the collection's setting."
        ),
    ),
) -> Any:
    """Upload and queue a file for ingestion into a collection.

    The collection row resolved above is what says how the file is read; the
    `ingestion` field departs from that for this one document and is recorded
    on it. No further permission is required for the override - `collections:edit`
    on this collection already allows changing its configuration outright.
    """
    collection = await access.writable(ctx, name)
    data = await file.read()
    return await rag_doc_svc.dispatch_upload(
        ctx=ctx,
        collection=collection,
        file_data=data,
        filename=file.filename or "unknown",
        replace=replace,
        vector_store=vector_store,
        override=parse_override(ingestion),
        organization_id=ctx.organization_id,
        # Link the document to the KB whose collection this is, the same way the
        # per-KB upload route does. Without it these rows carry no KB id, so a KB
        # delete keyed on it cannot reach them and leaves them orphaned (#1266).
        knowledge_base_id=collection.id,
    )


@router.get(
    "/documents",
    response_model=RAGTrackedDocumentList,
    dependencies=[Depends(require(Perm.COLLECTIONS_VIEW))],
)
async def list_rag_documents(
    rag_doc_svc: RAGDocumentSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
    collection_name: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """List a page of tracked RAG documents.

    Without `collection_name` this answers with the caller's collections -
    not, as it once did, with every document in the deployment - and it pages
    rather than serializing every row across them (#27).
    """
    collections = await access.readable_names_for(ctx, collection_name)
    return await rag_doc_svc.list_documents(collections=collections, skip=skip, limit=limit)


@router.get(
    "/documents/{doc_id}/download",
    response_model=None,
    dependencies=[Depends(require(Perm.COLLECTIONS_VIEW))],
)
async def download_rag_document(
    doc_id: str,
    rag_doc_svc: RAGDocumentSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> Any:
    """Download the original file for a tracked document."""
    doc = await access.readable_document(ctx, doc_id)
    file_path, filename, mime_type = await rag_doc_svc.get_download_info(str(doc.id))
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=mime_type,
        # The BFF forwards this rather than inventing one, which is why it is here:
        # a stored document does not change, and re-downloading it every time the
        # viewer is opened is a round trip for bytes the browser already has.
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.delete(
    "/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require(Perm.COLLECTIONS_EDIT))],
)
async def delete_rag_document(
    doc_id: str,
    rag_doc_svc: RAGDocumentSvc,
    ingestion_service: IngestionSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> None:
    """Delete a document from SQL, vector store, and file storage."""
    doc = await access.writable_document(ctx, doc_id)
    await rag_doc_svc.delete_document(str(doc.id), ingestion_service)


@router.post(
    "/documents/{doc_id}/retry",
    response_model=RAGRetryResponse,
    dependencies=[Depends(require(Perm.COLLECTIONS_EDIT))],
)
async def retry_ingestion(
    doc_id: str,
    rag_doc_svc: RAGDocumentSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> Any:
    """Retry a failed document ingestion."""
    tracked = await access.writable_document(ctx, doc_id)
    doc = await rag_doc_svc.retry_ingestion(str(tracked.id))
    return RAGRetryResponse(id=str(doc.id), status="processing", message="Retry queued")


@router.get(
    "/sync/logs",
    response_model=RAGSyncLogList,
    dependencies=[Depends(require(Perm.COLLECTIONS_VIEW))],
)
async def list_sync_logs(
    rag_sync_svc: RAGSyncSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
    collection_name: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> Any:
    """List sync operation logs for the caller's collections."""
    collections = await access.readable_names_for(ctx, collection_name)
    return await rag_sync_svc.list_sync_logs(collections=collections, limit=limit)


@router.post("/sync/local", response_model=RAGSyncResponse)
async def trigger_local_sync(
    request: RAGSyncRequest,
    rag_sync_svc: RAGSyncSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
    _: CurrentAppAdmin,
) -> Any:
    """Trigger a local directory sync via background task.

    The one route here that keeps the platform-admin role, because `path`
    names a directory on the server rather than anything a tenant owns: opening
    it to `collections:edit` would hand every member a read of arbitrary
    server files, ingested into a collection they can then search. It is a
    deployment-operations endpoint that happens to live under /rag, and it is
    still resolved against the caller's organization.
    """
    collection = await access.writable(ctx, request.collection_name)
    sync_log = await rag_sync_svc.start_local_sync(
        collection_name=collection.collection_name,
        mode=request.mode,
        path=request.path,
    )
    return RAGSyncResponse(
        id=str(sync_log.id),
        status="running",
        message=f"Sync started for '{collection.collection_name}' (mode={request.mode})",
    )


@router.delete(
    "/sync/{sync_id}",
    response_model=RAGMessageResponse,
    dependencies=[Depends(require(Perm.COLLECTIONS_EDIT))],
)
async def cancel_sync(
    sync_id: str,
    rag_sync_svc: RAGSyncSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> Any:
    """Cancel a running sync operation."""
    log = await access.sync_log(ctx, sync_id)
    await rag_sync_svc.cancel_sync(str(log.id))
    return RAGMessageResponse(message="Sync cancelled")


@router.get(
    "/sync/sources",
    response_model=SyncSourceList,
    dependencies=[Depends(require(Perm.COLLECTIONS_VIEW))],
)
async def list_sync_sources(
    sync_source_svc: SyncSourceSvc,
    ctx: Auth,
    collection_name: str | None = Query(None, description="Filter by KB collection name"),
) -> Any:
    """List sync sources for the active organization.

    Pass `collection_name` to see only sources assigned to a specific KB.
    Omit it to list all org-level integrations (assigned and unassigned).
    """
    return await sync_source_svc.list_sources(
        organization_id=ctx.organization_id,
        collection_name=collection_name,
    )


@router.post(
    "/sync/sources",
    response_model=SyncSourceRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.COLLECTIONS_EDIT))],
)
async def create_sync_source(
    data: SyncSourceCreate,
    sync_source_svc: SyncSourceSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> Any:
    """Create a new sync source configuration.

    Omit `collection_name` to create an org-level integration template
    that can later be cloned into one or more knowledge bases. Naming a
    collection the caller cannot write is refused: a sync writes *into* the
    collection, so pointing one at another tenant's is an injection, not a read.
    """
    if data.collection_name is not None:
        await access.writable(ctx, data.collection_name)
    return await sync_source_svc.create_source(data, ctx=ctx)


@router.post(
    "/sync/sources/{source_id}/clone",
    response_model=SyncSourceRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.COLLECTIONS_EDIT))],
)
async def clone_sync_source(
    source_id: str,
    data: SyncSourceClone,
    sync_source_svc: SyncSourceSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> Any:
    """Clone an existing integration into a different knowledge base.

    Credentials are decrypted from the source and re-encrypted for the clone,
    which is exactly why both ends are resolved first: the source must be this
    organization's, and so must the collection it is being pointed at.
    The clone is independent - its own schedule and sync history.
    """
    source = await access.sync_source(ctx, source_id)
    await access.writable(ctx, data.collection_name)
    return await sync_source_svc.clone_source(str(source.id), data, ctx=ctx)


@router.patch(
    "/sync/sources/{source_id}",
    response_model=SyncSourceRead,
    dependencies=[Depends(require(Perm.COLLECTIONS_EDIT))],
)
async def update_sync_source(
    source_id: str,
    data: SyncSourceUpdate,
    sync_source_svc: SyncSourceSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> Any:
    """Update an existing sync source configuration."""
    source = await access.sync_source(ctx, source_id)
    if data.collection_name is not None:
        await access.writable(ctx, data.collection_name)
    return await sync_source_svc.update_source(str(source.id), data, ctx=ctx)


@router.delete(
    "/sync/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require(Perm.COLLECTIONS_EDIT))],
)
async def delete_sync_source(
    source_id: str,
    sync_source_svc: SyncSourceSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> None:
    """Delete a sync source configuration."""
    source = await access.sync_source(ctx, source_id)
    await sync_source_svc.delete_source(str(source.id), ctx=ctx)


@router.post(
    "/sync/sources/{source_id}/trigger",
    response_model=RAGSyncResponse,
    dependencies=[Depends(require(Perm.COLLECTIONS_EDIT))],
)
async def trigger_sync_source(
    source_id: str,
    sync_source_svc: SyncSourceSvc,
    access: CollectionAccessSvc,
    ctx: Auth,
) -> Any:
    """Trigger a manual sync for a configured source."""
    source = await access.sync_source(ctx, source_id)
    sync_log = await sync_source_svc.trigger_sync(str(source.id))
    return RAGSyncResponse(
        id=str(sync_log.id),
        status="running",
        message=f"Sync triggered for source '{source_id}'",
    )


@router.get(
    "/sync/connectors",
    response_model=ConnectorList,
    dependencies=[Depends(require(Perm.COLLECTIONS_VIEW))],
)
async def list_connectors(sync_source_svc: SyncSourceSvc) -> Any:
    """List available sync connector types with their config schemas.

    Deployment configuration, not tenant data: which connectors are compiled in
    is the same answer for everyone, so there is nothing here to scope.
    """
    return sync_source_svc.list_connectors()
