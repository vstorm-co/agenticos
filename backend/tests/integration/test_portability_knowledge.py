"""Knowledge ZIPs preserve useful content without pretending to import an index."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models.rag_document import DocumentStatus
from app.repositories import portability_operation as operations
from app.repositories import rag_document_repo
from app.schemas.portability_operation import (
    BundleApplyCreate,
    BundleExportStart,
    BundleUploadStart,
)
from app.schemas.resource_bundle import BundleContentLayer, BundleImportChoice
from app.services.agent_registry import AgentRegistryService
from app.services.file_storage import LocalFileStorage
from app.services.ingestion_config import IngestionConfig
from app.services.knowledge_base import KnowledgeBaseService
from app.services.portability import PortableTransferService
from app.services.portability.knowledge import persistent_prefix
from app.services.rag.parsed_snapshot import ParsedSnapshotChunk
from app.services.rag_document import RAGDocumentService
from tests.integration.test_authoring import _owner
from tests.integration.test_portability_transfers import _chunks, _run

pytestmark = pytest.mark.anyio


async def test_knowledge_original_and_parsed_text_round_trip_stays_private_unindexed(
    db: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target, outsider = await _owner(db), await _owner(db), await _owner(db)
    storage = LocalFileStorage(tmp_path)
    kb = await KnowledgeBaseService(db).create_portable_snapshot(
        ctx=source,
        name="Research",
        description="Source knowledge",
        ingestion_config=IngestionConfig(),
        embedding_model="text-embedding-3-small",
        embedding_provider="openai",
        embedding_dim=1536,
        embedding_secret_id=None,
        embedding_endpoint_id=None,
    )
    original = b"Exact original document\n"
    await storage.save_at("source/original.txt", original)
    parsed = ParsedSnapshotChunk(page_num=1, chunk_num=0, content="  Exact parsed αβ\n")
    await storage.save_at("source/parsed.jsonl", (parsed.model_dump_json() + "\n").encode())
    await rag_document_repo.create(
        db,
        collection_name=kb.collection_name,
        filename="research.txt",
        filesize=len(original),
        filetype="txt",
        storage_path="source/original.txt",
        parsed_content_path="source/parsed.jsonl",
        status=DocumentStatus.STORED,
        organization_id=source.organization_id,
        knowledge_base_id=kb.id,
        ingestion_config=IngestionConfig().model_dump(mode="json"),
    )
    agent = await AgentRegistryService(db).create(
        source, AgentSpec(name="Researcher", collection_ids=[kb.id]), choose_model=False
    )
    service = PortableTransferService(db, storage=storage)
    preview = await service.portability.export_agent(source, agent.id, metadata_only=True)
    assert BundleContentLayer.KB_INDEX not in set().union(
        *(option.layers for option in preview.options)
    )
    ticket = await service.start_export(
        source,
        BundleExportStart(
            request_id=uuid4(),
            root_kind="agent",
            root_id=agent.id,
            resources={option.key: option.layers for option in preview.options},
        ),
    )
    await _run(db, service, ticket.id)
    archive = b"".join([piece async for piece in await service.download(source, ticket.id)])
    upload = await service.start_upload(
        target,
        BundleUploadStart(request_id=uuid4(), filename="knowledge.zip", size_bytes=len(archive)),
    )
    await service.upload(target, upload.id, _chunks(archive))
    await _run(db, service, upload.id)
    review = await service.get(target, upload.id)
    assert review.preview is not None
    choices = {
        item.key: BundleImportChoice(action="create") for item in review.preview.bundle.resources
    }
    request = BundleApplyCreate(expected_revision=review.revision, choices=choices)
    await service.apply(target, upload.id, request)
    await _run(db, service, upload.id)
    ready = await service.get(target, upload.id)
    assert ready.receipt is not None
    copied_id = ready.receipt.created[f"knowledge_base/{kb.id}"]
    copied = await KnowledgeBaseService(db).get(copied_id, ctx=target)
    assert copied.scope == "personal" and copied.owner_user_id == target.subject_id
    assert copied.collection_name != kb.collection_name and copied.embedding_secret_id is None
    rows, total = await rag_document_repo.get_for_kb(db, copied_id)
    assert total == 1 and rows[0].status == DocumentStatus.STORED
    document = rows[0]
    assert document.vector_document_id is None and document.chunk_count == 0
    assert document.storage_path and document.parsed_content_path
    assert await storage.load(document.storage_path) == original
    monkeypatch.setattr("app.services.rag_document.get_file_storage", lambda: storage)
    vector_store = AsyncMock()
    rendered = await RAGDocumentService(db).get_parsed_content(str(document.id), vector_store)
    assert rendered.chunk_count == 1 and rendered.pages[0].chunks == [parsed.content]
    vector_store.get_document_chunks.assert_not_awaited()
    with pytest.raises(NotFoundError):
        await KnowledgeBaseService(db).get(copied_id, ctx=outsider)
    assert (await service.apply(target, upload.id, request)).receipt == ready.receipt
    assert (await rag_document_repo.get_for_kb(db, copied_id))[1] == 1
    # Expiring transfer staging must preserve the files now owned by documents.
    operation = await operations.get_for_worker(db, upload.id)
    assert operation is not None
    operation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()
    await service.sweep()
    assert await storage.exists(document.storage_path) and await storage.exists(
        document.parsed_content_path
    )
    prepared = await rag_document_repo.update_status(
        db,
        document.id,
        status=DocumentStatus.PROCESSING,
        expected_attempt=document.ingestion_attempt,
        ingestion_config=IngestionConfig(chunk_size=512).model_dump(mode="json"),
    )
    assert prepared is not None and prepared.ingestion_config["chunk_size"] == 512
    prepared = await rag_document_repo.update_status(
        db,
        document.id,
        status=DocumentStatus.STORED,
        ingestion_config=IngestionConfig(chunk_size=1024).model_dump(mode="json"),
    )
    assert prepared is not None and prepared.ingestion_config["chunk_size"] == 1024
    # Ordinary document deletion returns both owned objects for durable cleanup.
    deleted = await rag_document_repo.delete_with_vectors(db, document.id)
    assert set(deleted.storage_paths) == {document.storage_path, document.parsed_content_path}
    assert document.storage_path.startswith(persistent_prefix(upload.id))


@pytest.mark.parametrize("failure", [ConflictError, asyncio.CancelledError])
async def test_failed_worker_rolls_back_all_rows_and_expiry_collects_unowned_files(
    db: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: type[BaseException]
) -> None:
    from hashlib import sha256
    from io import BytesIO

    from app.repositories import solution_installation as receipts
    from app.schemas.resource_bundle import BundleAsset, BundleResourceKind
    from app.services.portability.archive import write_bundle
    from app.services.portability.content import KnowledgeBaseContent, KnowledgeDocumentContent
    from app.services.portability.snapshots import agent_snapshot

    target = await _owner(db)
    source_kb = uuid4()
    source_doc = uuid4().hex
    key = f"knowledge_base/{source_kb}"
    data = (
        ParsedSnapshotChunk(page_num=1, chunk_num=0, content="private exact text").model_dump_json()
        + "\n"
    ).encode()
    digest = sha256(data).hexdigest()
    file = tmp_path / "snapshot.jsonl"
    file.write_bytes(data)
    bundle = agent_snapshot(
        AgentSpec(name="Imported researcher", collection_ids=[source_kb]), source_id=uuid4()
    )
    content = KnowledgeBaseContent(
        name="Imported knowledge",
        embedding_model="text-embedding-3-small",
        embedding_provider="openai",
        embedding_dim=1536,
        documents=(
            KnowledgeDocumentContent(
                id=source_doc, filename="example.txt", filesize=10, filetype="txt"
            ),
        ),
    )
    bundle = bundle.model_copy(
        update={
            "resources": tuple(
                resource.model_copy(
                    update={
                        "definition": content.model_dump(mode="json"),
                        "included": frozenset(
                            {BundleContentLayer.DEFINITION, BundleContentLayer.KB_PARSED_TEXT}
                        ),
                    }
                )
                if resource.kind == BundleResourceKind.KNOWLEDGE_BASE
                else resource
                for resource in bundle.resources
            ),
            "assets": (
                BundleAsset(
                    resource=key,
                    layer=BundleContentLayer.KB_PARSED_TEXT,
                    name=source_doc,
                    sha256=digest,
                    size_bytes=len(data),
                    media_type="application/x-ndjson",
                ),
            ),
        }
    )
    archive = BytesIO()
    write_bundle(archive, bundle, {digest: file})
    raw = archive.getvalue()
    storage = LocalFileStorage(tmp_path / "storage")
    service = PortableTransferService(db, storage=storage)
    upload = await service.start_upload(
        target, BundleUploadStart(request_id=uuid4(), filename="test.zip", size_bytes=len(raw))
    )
    await service.upload(target, upload.id, _chunks(raw))
    await _run(db, service, upload.id)
    review = await service.get(target, upload.id)
    assert review.preview is not None
    await service.apply(
        target,
        upload.id,
        BundleApplyCreate(
            expected_revision=review.revision,
            choices={
                resource.key: BundleImportChoice(action="create") for resource in bundle.resources
            },
        ),
    )
    before = {row.id for row in await KnowledgeBaseService(db).list_accessible(target)}
    fence = service._fence

    async def lost_lease(*_args: object, **_kwargs: object) -> None:
        if failure is ConflictError:
            raise ConflictError(message="worker lease ended")
        raise asyncio.CancelledError("worker lease ended")

    monkeypatch.setattr(service, "_fence", lost_lease)
    with pytest.raises(failure, match="lease ended"):
        async with db.begin_nested():
            await _run(db, service, upload.id)
    monkeypatch.setattr(service, "_fence", fence)
    assert {row.id for row in await KnowledgeBaseService(db).list_accessible(target)} == before
    assert (
        await receipts.get(
            db,
            organization_id=target.organization_id,
            user_id=target.subject_id,
            key=f"bundle-{upload.id.hex}",
        )
        is None
    )
    stored = f"{persistent_prefix(upload.id, key)}{source_doc}/kb_parsed_text-{digest}"
    assert await storage.exists(stored)
    operation = await operations.get_for_worker(db, upload.id)
    assert operation is not None
    operation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()
    await service.sweep()
    assert not await storage.exists(stored)


@pytest.mark.security
async def test_streamed_chunk_reader_pages_text_ids_and_keeps_tenant_and_base_scope(
    engine: AsyncEngine,
) -> None:
    import json

    from sqlalchemy import text

    from app.db.vector_tables import VectorScope
    from app.services.embedding_resolution import ResolvedEmbeddings
    from app.services.rag.config import RAGSettings
    from app.services.rag.embeddings import EmbeddingService
    from app.services.rag.vectorstore import PgVectorStore

    tenant, kb_id, other_tenant, other_kb = uuid4(), uuid4(), uuid4(), uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TABLE rag_portable_read (id VARCHAR(100) PRIMARY KEY, parent_doc_id VARCHAR(100), content TEXT, metadata JSONB)"
            )
        )
        values = [
            {
                "id": f"chunk-{index:04d}",
                "doc": "source-doc",
                "content": str(index),
                "metadata": json.dumps(
                    {
                        "organization_id": str(tenant),
                        "knowledge_base_id": str(kb_id),
                        "page_num": 1,
                        "chunk_num": index,
                    }
                ),
            }
            for index in range(205)
        ]
        for index, metadata in enumerate(
            (
                {"organization_id": str(other_tenant), "knowledge_base_id": str(kb_id)},
                {"organization_id": str(tenant), "knowledge_base_id": str(other_kb)},
                {"organization_id": str(tenant)},
            )
        ):
            values.append(
                {
                    "id": f"foreign-{index}",
                    "doc": "source-doc",
                    "content": "private foreign text",
                    "metadata": json.dumps(metadata),
                }
            )
        await connection.execute(
            text(
                "INSERT INTO rag_portable_read (id,parent_doc_id,content,metadata) VALUES (:id,:doc,:content,CAST(:metadata AS JSONB))"
            ),
            values,
        )

    async def unresolved(_collection: str, _organization: UUID | None) -> ResolvedEmbeddings | None:
        return None

    settings = RAGSettings()
    store = PgVectorStore(settings, EmbeddingService(settings), unresolved, engine=engine)
    scope = VectorScope(tenant=tenant, knowledge_base_id=kb_id, takes_unfiled=False)
    chunks = [
        chunk async for chunk in store.iter_document_chunks("portable_read", "source-doc", scope)
    ]
    assert len(chunks) == 205
    assert [chunk.content for chunk in chunks] == [str(index) for index in range(205)]
    assert [
        chunk async for chunk in store.iter_document_chunks("missing_portable", "source-doc", scope)
    ] == []
