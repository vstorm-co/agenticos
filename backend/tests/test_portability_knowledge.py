"""Knowledge assets have bounded content and document-owned storage lifetimes."""

from collections.abc import AsyncGenerator
from hashlib import sha256
from pathlib import Path
from typing import TypedDict
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import BadRequestError, ConflictError
from app.core.permissions import AuthContext
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.schemas.resource_bundle import (
    BundleAsset,
    BundleResource,
    BundleResourceKind,
)
from app.schemas.resource_bundle import (
    BundleContentLayer as Layer,
)
from app.services.file_storage import LocalFileStorage
from app.services.ingestion_config import IngestionConfig
from app.services.portability import knowledge
from app.services.portability.content import KnowledgeBaseContent, KnowledgeDocumentContent
from app.services.rag.models import DocumentChunk
from app.services.rag.parsed_snapshot import ParsedSnapshotChunk
from app.services.rag.vectorstore import BaseVectorStore

pytestmark = pytest.mark.anyio


class _SnapshotArguments(TypedDict):
    name: str
    description: str | None
    ingestion_config: IngestionConfig
    embedding_model: str
    embedding_provider: str
    embedding_dim: int
    embedding_secret_id: UUID | None
    embedding_endpoint_id: UUID | None


def _content() -> KnowledgeBaseContent:
    return KnowledgeBaseContent(
        name="Research",
        embedding_model="text-embedding-3-small",
        embedding_provider="openai",
        embedding_dim=1536,
    )


def _resource() -> BundleResource:
    identity = uuid4()
    return BundleResource(
        key=f"knowledge_base/{identity}",
        kind=BundleResourceKind.KNOWLEDGE_BASE,
        name="Research",
        source_id=identity,
        definition=_content().model_dump(mode="json"),
        included=frozenset({Layer.DEFINITION, Layer.KB_DOCUMENTS, Layer.KB_PARSED_TEXT}),
    )


def _kb(resource: BundleResource, ctx: AuthContext) -> KnowledgeBase:
    return KnowledgeBase(
        id=resource.source_id,
        name="Research",
        scope="personal",
        collection_name="kb_test",
        organization_id=ctx.organization_id,
        owner_user_id=ctx.subject_id,
    )


def test_asset_contract_refuses_undeclared_missing_index_and_mismatched_original(
    tmp_path: Path,
) -> None:
    resource = _resource()
    identity = uuid4().hex
    doc = KnowledgeDocumentContent(
        id=identity, filename="../display-only.txt", filesize=3, filetype="txt"
    )
    content = _content().model_copy(update={"documents": (doc,)})
    resource = resource.model_copy(update={"definition": content.model_dump(mode="json")})
    asset = BundleAsset(
        resource=resource.key,
        layer=Layer.KB_DOCUMENTS,
        name=identity,
        sha256="a" * 64,
        size_bytes=3,
        media_type="text/plain",
    )
    assert knowledge.validate_knowledge_assets(resource, (asset,), {}) == 0
    for changed in (
        asset.model_copy(update={"name": "unknown"}),
        asset.model_copy(update={"layer": Layer.KB_INDEX}),
        asset.model_copy(update={"size_bytes": 4}),
    ):
        with pytest.raises(BadRequestError):
            knowledge.validate_knowledge_assets(resource, (changed,), {})
    with pytest.raises(BadRequestError):
        knowledge.validate_knowledge_assets(resource, (), {})
    path = tmp_path / "parsed"
    path.write_text('{"page_num":0,"chunk_num":0,"content":"exact"}\n')
    parsed = asset.model_copy(update={"layer": Layer.KB_PARSED_TEXT})
    assert knowledge.validate_knowledge_assets(resource, (parsed,), {parsed.sha256: path}) == 1


async def test_export_streams_originals_and_vectors_without_loading_whole_documents(
    mock_db_session: AsyncMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    resource = _resource()
    kb = _kb(resource, ctx)
    storage = LocalFileStorage(tmp_path / "storage")
    await storage.save_at("original", b"exact original")
    doc = RAGDocument(
        id=uuid4(),
        filename="duplicate.txt",
        filesize=14,
        filetype="txt",
        storage_path="original",
        ingestion_config={},
        status=DocumentStatus.DONE,
        vector_document_id="vector-1",
        chunk_count=1,
    )
    monkeypatch.setattr(knowledge.KnowledgeBaseService, "get", AsyncMock(return_value=kb))
    listing = AsyncMock(side_effect=[[doc], []])
    monkeypatch.setattr(knowledge.rag_document_repo, "portable_page", listing)
    closed: list[bool] = []

    async def chunks() -> AsyncGenerator[DocumentChunk]:
        try:
            yield DocumentChunk(page_num=2, chunk_num=0, content="exact αβ")
        finally:
            closed.append(True)

    vectors = MagicMock(spec=BaseVectorStore)
    vectors.iter_document_chunks.return_value = chunks()
    work = tmp_path / "staging"
    work.mkdir()
    exported, assets, files, count = await knowledge.KnowledgeTransfer(
        mock_db_session, storage=storage, vectors=vectors
    ).export(ctx, resource, frozenset({Layer.KB_DOCUMENTS, Layer.KB_PARSED_TEXT}), work)
    assert count == 1 and len(assets) == 2 and closed == [True]
    assert knowledge.validate_knowledge_assets(exported, assets, files) == 1
    original = next(asset for asset in assets if asset.layer == Layer.KB_DOCUMENTS)
    assert files[original.sha256].read_bytes() == b"exact original"
    assert listing.await_args is not None
    assert listing.await_args.kwargs["after"] == doc.id
    vectors.get_document_chunks.assert_not_called()
    assert "storage_path" not in str(exported.definition)
    assert "vector-1" not in str(exported.definition)


async def test_export_refuses_changed_original_and_size_overrun(
    mock_db_session: AsyncMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    resource = _resource()
    monkeypatch.setattr(
        knowledge.KnowledgeBaseService, "get", AsyncMock(return_value=_kb(resource, ctx))
    )
    storage = LocalFileStorage(tmp_path / "storage")
    await storage.save_at("original", b"abcd")
    doc = RAGDocument(
        id=uuid4(),
        filename="file.txt",
        filesize=3,
        filetype="txt",
        storage_path="original",
        ingestion_config={},
    )
    monkeypatch.setattr(knowledge.rag_document_repo, "portable_page", AsyncMock(return_value=[doc]))
    service = knowledge.KnowledgeTransfer(mock_db_session, storage=storage)
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(ConflictError):
        await service.export(ctx, resource, frozenset({Layer.KB_DOCUMENTS}), work)
    with pytest.raises(BadRequestError):
        await service.export(ctx, resource, frozenset({Layer.KB_DOCUMENTS}), work, asset_budget=1)


async def test_import_each_document_owns_its_original_and_snapshot_even_for_identical_bytes(
    mock_db_session: AsyncMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    resource = _resource()
    kb = _kb(resource, ctx)
    assert kb.id is not None
    documents = tuple(
        KnowledgeDocumentContent(id=uuid4().hex, filename="same.txt", filesize=4, filetype="txt")
        for _ in range(2)
    )
    resource = resource.model_copy(
        update={
            "definition": _content()
            .model_copy(update={"documents": documents})
            .model_dump(mode="json")
        }
    )
    raw = b"same"
    digest = sha256(raw).hexdigest()
    path = tmp_path / digest
    path.write_bytes(raw)
    assets = tuple(
        BundleAsset(
            resource=resource.key,
            layer=Layer.KB_DOCUMENTS,
            name=doc.id,
            sha256=digest,
            size_bytes=4,
            media_type="text/plain",
        )
        for doc in documents
    )
    storage = LocalFileStorage(tmp_path / "storage")
    monkeypatch.setattr(knowledge.KnowledgeBaseService, "get", AsyncMock(return_value=kb))
    create = AsyncMock()
    monkeypatch.setattr(knowledge.rag_document_repo, "create", create)
    operation = uuid4()
    await knowledge.KnowledgeTransfer(mock_db_session, storage=storage).import_documents(
        ctx,
        operation=operation,
        resource=resource,
        kb_id=kb.id,
        assets=assets,
        files={digest: path},
    )
    paths = [call.kwargs["storage_path"] for call in create.await_args_list]
    assert len(set(paths)) == 2
    for call in create.await_args_list:
        assert call.kwargs["status"] == DocumentStatus.STORED
        assert call.kwargs["knowledge_base_id"] == kb.id
        assert await storage.load(call.kwargs["storage_path"]) == raw
    await storage.delete(paths[0])
    assert await storage.exists(paths[1])


async def test_parsed_only_and_unavailable_layers_do_not_copy_originals(
    mock_db_session: AsyncMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    resource = _resource()
    storage = LocalFileStorage(tmp_path / "storage")
    line = (
        ParsedSnapshotChunk(page_num=0, chunk_num=0, content="snapshot").model_dump_json().encode()
        + b"\n"
    )
    await storage.save_at("parsed", line)
    document = RAGDocument(
        id=uuid4(),
        filename="snapshot.txt",
        filesize=10,
        filetype="txt",
        status=DocumentStatus.STORED,
        parsed_content_path="parsed",
        ingestion_config={},
    )
    pending = RAGDocument(
        id=uuid4(),
        filename="pending.txt",
        filesize=1,
        filetype="txt",
        status=DocumentStatus.PROCESSING,
        ingestion_config={},
    )
    monkeypatch.setattr(
        knowledge.KnowledgeBaseService, "get", AsyncMock(return_value=_kb(resource, ctx))
    )
    listing = AsyncMock(side_effect=[[document, pending], []])
    monkeypatch.setattr(knowledge.rag_document_repo, "portable_page", listing)
    service = knowledge.KnowledgeTransfer(mock_db_session, storage=storage)
    assert await service.export(ctx, resource, frozenset({Layer.DEFINITION}), tmp_path) == (
        resource,
        (),
        {},
        0,
    )
    exported, assets, files, count = await service.export(
        ctx, resource, frozenset({Layer.KB_PARSED_TEXT}), tmp_path
    )
    assert count == 1 and len(assets) == 1 and assets[0].layer == Layer.KB_PARSED_TEXT
    assert knowledge.validate_knowledge_assets(exported, assets, files) == 1
    listing.side_effect = [[pending], []]
    exported, assets, _, count = await service.export(
        ctx, resource, frozenset({Layer.KB_DOCUMENTS}), tmp_path
    )
    assert assets == () and count == 0


@pytest.mark.security
async def test_stream_limits_close_reader_and_snapshot_budget_applies_across_documents(
    mock_db_session: AsyncMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    resource = _resource()
    storage = LocalFileStorage(tmp_path / "storage")
    monkeypatch.setattr(
        knowledge.KnowledgeBaseService, "get", AsyncMock(return_value=_kb(resource, ctx))
    )
    doc = RAGDocument(
        id=uuid4(),
        filename="file.txt",
        filesize=0,
        filetype="txt",
        storage_path=None,
        status=DocumentStatus.DONE,
        vector_document_id="vec",
        ingestion_config={},
    )
    listing = AsyncMock(return_value=[doc])
    monkeypatch.setattr(knowledge.rag_document_repo, "portable_page", listing)
    closed: list[bool] = []

    async def chunks() -> AsyncGenerator[DocumentChunk]:
        try:
            yield DocumentChunk(content="text")
        finally:
            closed.append(True)

    vectors = MagicMock(spec=BaseVectorStore)
    vectors.iter_document_chunks.return_value = chunks()
    # Lazy default construction must still use an injected keyless reader only.
    monkeypatch.setattr(knowledge, "unpooled_vector_store", lambda *_args: vectors)
    service = knowledge.KnowledgeTransfer(mock_db_session, storage=storage)
    with pytest.raises(BadRequestError, match="limit"):
        await service.export(
            ctx, resource, frozenset({Layer.KB_PARSED_TEXT}), tmp_path, asset_budget=1
        )
    assert closed == [True]
    line = (
        ParsedSnapshotChunk(page_num=0, chunk_num=0, content="snapshot").model_dump_json().encode()
        + b"\n"
    )
    await storage.save_at("parsed", line)
    docs = [
        RAGDocument(
            id=uuid4(),
            filename="one.txt",
            filesize=0,
            filetype="txt",
            parsed_content_path="parsed",
            status=DocumentStatus.STORED,
            ingestion_config={},
        )
        for _ in range(2)
    ]
    listing.return_value = docs
    monkeypatch.setattr(knowledge, "MAX_SNAPSHOT_CHUNKS", 1)
    with pytest.raises(BadRequestError, match="10,000"):
        await service.export(ctx, resource, frozenset({Layer.KB_PARSED_TEXT}), tmp_path)
    monkeypatch.setattr(knowledge, "MAX_SNAPSHOT_CHUNKS", 10_000)
    monkeypatch.setattr(knowledge, "MAX_KB_DOCUMENTS", 1)
    with pytest.raises(BadRequestError, match="1,000"):
        await service.export(ctx, resource, frozenset({Layer.KB_PARSED_TEXT}), tmp_path)
    declarations = tuple(
        KnowledgeDocumentContent(id=doc.id.hex, filename=doc.filename, filesize=0, filetype="txt")
        for doc in docs
    )
    resource = resource.model_copy(
        update={
            "definition": _content()
            .model_copy(update={"documents": declarations})
            .model_dump(mode="json")
        }
    )
    path = tmp_path / "verify"
    path.write_bytes(line)
    assets = tuple(
        BundleAsset(
            resource=resource.key,
            layer=Layer.KB_PARSED_TEXT,
            name=doc.id,
            sha256="a" * 64,
            size_bytes=len(line),
            media_type="application/x-ndjson",
        )
        for doc in declarations
    )
    monkeypatch.setattr(knowledge, "MAX_SNAPSHOT_CHUNKS", 1)
    with pytest.raises(BadRequestError, match="10,000"):
        knowledge.validate_knowledge_assets(resource, assets, {"a" * 64: path})


def test_definition_refuses_index_claims_and_duplicate_document_ids() -> None:
    from pydantic import ValidationError

    from app.services.portability.contracts import definition_model

    resource = _resource().model_copy(
        update={"included": frozenset({Layer.DEFINITION, Layer.KB_INDEX})}
    )
    with pytest.raises(BadRequestError, match="indexes"):
        definition_model(resource)
    doc = KnowledgeDocumentContent(id=uuid4().hex, filename="same.txt", filesize=1, filetype="txt")
    with pytest.raises(ValidationError, match="once"):
        KnowledgeBaseContent.model_validate({**_content().model_dump(), "documents": [doc, doc]})


@pytest.mark.security
async def test_private_snapshot_creation_checks_permission_and_mapped_endpoint(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.exceptions import AuthorizationError
    from app.db.models.local_service import LocalService
    from app.services import knowledge_base as domain
    from app.services.local_service import LocalServiceService

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    service = domain.KnowledgeBaseService(mock_db_session)
    secret, endpoint = uuid4(), uuid4()
    row = KnowledgeBase(id=uuid4(), name="Source")
    create = AsyncMock(return_value=row)
    monkeypatch.setattr(domain.knowledge_base_repo, "create", create)
    claim = AsyncMock()
    monkeypatch.setattr(domain.CollectionAccessService, "claim", claim)
    check_secret = AsyncMock()
    monkeypatch.setattr(service, "_check_embedding_secret", check_secret)
    local = LocalService(id=endpoint, kind="embedding", provider="openai", name="Destination")
    monkeypatch.setattr(LocalServiceService, "get_visible", AsyncMock(return_value=local))
    arguments: _SnapshotArguments = {
        "name": "Imported",
        "description": None,
        "ingestion_config": IngestionConfig(),
        "embedding_model": "text-embedding-3-small",
        "embedding_provider": "openai",
        "embedding_dim": 1536,
        "embedding_secret_id": None,
        "embedding_endpoint_id": endpoint,
    }
    assert await service.create_portable_snapshot(ctx=ctx, **arguments) is row
    arguments["embedding_secret_id"] = secret
    with pytest.raises(BadRequestError, match="either"):
        await service.create_portable_snapshot(ctx=ctx, **arguments)
    arguments["embedding_endpoint_id"] = None
    assert await service.create_portable_snapshot(ctx=ctx, **arguments) is row
    check_secret.assert_awaited_once()
    arguments["embedding_secret_id"] = None
    arguments["embedding_endpoint_id"] = endpoint
    assert create.await_args is not None
    assert create.await_args.kwargs["scope"] == "personal"
    assert create.await_args.kwargs["owner_user_id"] == ctx.subject_id
    assert create.await_args.kwargs["collection_name"].startswith("portable_")
    local.kind = "ocr"
    with pytest.raises(BadRequestError, match="embedding endpoint"):
        await service.create_portable_snapshot(ctx=ctx, **arguments)
    with pytest.raises(AuthorizationError):
        await service.create_portable_snapshot(
            ctx=AuthContext(user_id=uuid4(), organization_id=ctx.organization_id, role="viewer"),
            **arguments,
        )
    with pytest.raises(AuthorizationError, match="signed-in"):
        await service.create_portable_snapshot(
            ctx=AuthContext(user_id=None, organization_id=ctx.organization_id, role="owner"),
            **arguments,
        )


async def test_selected_layers_require_zip_and_transfer_chunk_cap_is_aggregate(
    mock_db_session: AsyncMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.schemas.resource_bundle import (
        BundleDownloadCreate,
        BundlePreview,
        BundleResourceOption,
        ResourceBundle,
    )
    from app.services.portability.facade import PortabilityService

    resource = _resource().model_copy(update={"included": frozenset({Layer.DEFINITION})})
    bundle = ResourceBundle(roots=(resource.key,), resources=(resource,))
    preview = BundlePreview(
        bundle=bundle,
        options=(
            BundleResourceOption(
                key=resource.key,
                available=True,
                layers=frozenset({Layer.DEFINITION, Layer.KB_PARSED_TEXT}),
            ),
        ),
    )
    service = PortabilityService(mock_db_session)
    monkeypatch.setattr(service, "export_agent", AsyncMock(return_value=preview))
    monkeypatch.setattr(service, "_source", AsyncMock(return_value=(preview.options[0], resource)))
    selection = BundleDownloadCreate(
        resources={resource.key: frozenset({Layer.DEFINITION, Layer.KB_PARSED_TEXT})}
    )
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    with pytest.raises(BadRequestError, match="ZIP"):
        await service.selected_agent(ctx, uuid4(), selection)
    monkeypatch.setattr(
        knowledge.KnowledgeTransfer, "export", AsyncMock(return_value=(resource, (), {}, 10_001))
    )
    with pytest.raises(BadRequestError, match="10,000"):
        await service.selected_agent(ctx, uuid4(), selection, asset_directory=tmp_path)


async def test_inline_knowledge_definition_can_be_empty_but_never_claim_document_content(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.spec import AgentSpec
    from app.schemas.resource_bundle import BundleImportChoice, BundleImportCreate
    from app.services.portability.facade import PortabilityService
    from app.services.portability.snapshots import agent_snapshot
    from tests.test_portability_flow import receipts

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    service = PortabilityService(mock_db_session)
    receipts(monkeypatch)
    monkeypatch.setattr(service, "_create", AsyncMock(side_effect=lambda *_args: uuid4()))
    resource = _resource().model_copy(update={"included": frozenset({Layer.DEFINITION})})
    assert resource.source_id is not None
    bundle = agent_snapshot(
        AgentSpec(name="Researcher", collection_ids=[resource.source_id]), source_id=uuid4()
    )
    bundle = bundle.model_copy(
        update={
            "resources": tuple(
                resource if item.key == resource.key else item for item in bundle.resources
            )
        }
    )
    request = BundleImportCreate(
        operation_id=uuid4(),
        bundle=bundle,
        choices={item.key: BundleImportChoice(action="create") for item in bundle.resources},
    )
    assert len((await service.import_agent(ctx, request)).created) == 2
    doc = KnowledgeDocumentContent(id=uuid4().hex, filename="file.txt", filesize=1, filetype="txt")
    resource = resource.model_copy(
        update={
            "definition": _content()
            .model_copy(update={"documents": (doc,)})
            .model_dump(mode="json")
        }
    )
    bundle = bundle.model_copy(
        update={
            "resources": tuple(
                resource if item.key == resource.key else item for item in bundle.resources
            )
        }
    )
    with pytest.raises(BadRequestError, match="complete bundle"):
        await service.import_agent(
            ctx, request.model_copy(update={"bundle": bundle, "operation_id": uuid4()})
        )


def test_zip_reader_refuses_aggregate_chunk_overrun_before_applying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.spec import AgentSpec
    from app.schemas.resource_bundle import ResourceBundle
    from app.services.portability import transfers
    from app.services.portability.archive import write_bundle
    from app.services.portability.file_bundle import hydrate_text
    from app.services.portability.snapshots import agent_snapshot

    resource = _resource().model_copy(update={"included": frozenset({Layer.DEFINITION})})
    assert resource.source_id is not None
    bundle = agent_snapshot(
        AgentSpec(name="Researcher", collection_ids=[resource.source_id]), source_id=uuid4()
    )
    bundle = bundle.model_copy(
        update={
            "resources": tuple(
                resource if item.key == resource.key else item for item in bundle.resources
            )
        }
    )
    path = tmp_path / "archive.zip"
    with path.open("w+b") as target:
        write_bundle(target, bundle, {})
    monkeypatch.setattr(transfers, "validate_knowledge_assets", lambda *_args: 10_001)
    with pytest.raises(BadRequestError, match="10,000"):
        transfers._read_zip(path, tmp_path)
    asset = BundleAsset(
        resource=resource.key,
        layer=Layer.KB_INDEX,
        name="index",
        sha256="a" * 64,
        size_bytes=1,
        media_type="application/octet-stream",
    )
    invalid = ResourceBundle.model_construct(
        roots=(resource.key,), resources=(resource,), assets=(asset,)
    )
    with pytest.raises(BadRequestError, match="indexes"):
        hydrate_text(invalid, {})


async def test_expiry_removes_unused_resource_prefix_but_keeps_created_documents(
    mock_db_session: AsyncMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.spec import AgentSpec
    from app.schemas.resource_bundle import BundleImportRead
    from app.services.portability import transfers
    from app.services.portability.snapshots import agent_snapshot
    from tests.test_portability_transfers import _row

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    resource = _resource()
    assert resource.source_id is not None
    bundle = agent_snapshot(
        AgentSpec(name="Researcher", collection_ids=[resource.source_id]), source_id=uuid4()
    )
    row = _row(ctx)
    row.status = "ready"
    row.manifest = bundle.model_dump(mode="json")
    row.result = BundleImportRead(
        roots={bundle.roots[0]: uuid4()}, created={}, reused={resource.key: uuid4()}, skipped=()
    ).model_dump(mode="json")
    storage = LocalFileStorage(tmp_path)
    path = knowledge.persistent_prefix(row.id, resource.key) + "abandoned"
    await storage.save_at(path, b"orphaned attempt")
    monkeypatch.setattr(transfers.operations, "expired", AsyncMock(return_value=[row]))
    monkeypatch.setattr(transfers.operations, "get_for_worker", AsyncMock(return_value=row))
    deleted = AsyncMock()
    monkeypatch.setattr(transfers.operations, "delete", deleted)
    await transfers.PortableTransferService(mock_db_session, storage=storage).sweep()
    assert not await storage.exists(path)
    deleted.assert_awaited_once()


async def test_export_refuses_concurrent_document_or_vector_replacement(
    mock_db_session: AsyncMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    resource = _resource()
    storage = LocalFileStorage(tmp_path / "storage")
    await storage.save_at("original", b"x")
    document = RAGDocument(
        id=uuid4(),
        filename="file.txt",
        filesize=1,
        filetype="txt",
        storage_path="original",
        status=DocumentStatus.DONE,
        vector_document_id="vec",
        chunk_count=2,
        ingestion_config={},
    )
    monkeypatch.setattr(
        knowledge.KnowledgeBaseService, "get", AsyncMock(return_value=_kb(resource, ctx))
    )
    monkeypatch.setattr(
        knowledge.rag_document_repo, "portable_page", AsyncMock(return_value=[document])
    )
    monkeypatch.setattr(
        knowledge.rag_document_repo, "portable_unchanged", AsyncMock(return_value=False)
    )
    service = knowledge.KnowledgeTransfer(mock_db_session, storage=storage)
    with pytest.raises(ConflictError, match="document changed"):
        await service.export(ctx, resource, frozenset({Layer.KB_DOCUMENTS}), tmp_path)

    async def one_chunk() -> AsyncGenerator[DocumentChunk]:
        yield DocumentChunk(content="only one")

    vectors = MagicMock(spec=BaseVectorStore)
    vectors.iter_document_chunks.return_value = one_chunk()
    service.vectors = vectors
    with pytest.raises(ConflictError, match="indexed chunks changed"):
        await service.export(ctx, resource, frozenset({Layer.KB_PARSED_TEXT}), tmp_path)


@pytest.mark.parametrize("case", ["valid", "no_kb", "missing_kb", "too_big", "parsed_only"])
async def test_explicit_indexing_uses_destination_settings_and_refuses_unusable_originals(
    mock_db_session: AsyncMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    from app.core.config import settings
    from app.core.exceptions import NotFoundError
    from app.services import rag_document as domain

    storage = LocalFileStorage(tmp_path)
    await storage.save_at("original", b"original")
    doc = RAGDocument(
        id=uuid4(),
        collection_name="destination",
        filename="file.txt",
        filetype="txt",
        filesize=8,
        storage_path="original",
        status=DocumentStatus.STORED,
        knowledge_base_id=uuid4(),
        organization_id=uuid4(),
        ingestion_attempt=1,
        ingestion_config={"chunk_size": 1024},
    )
    kb = KnowledgeBase(
        id=doc.knowledge_base_id,
        ingestion_config=IngestionConfig(chunk_size=512).model_dump(mode="json"),
    )
    if case == "no_kb":
        doc.knowledge_base_id = doc.organization_id = None
    elif case == "too_big":
        doc.filesize = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024 + 1
    elif case == "parsed_only":
        doc.storage_path = None
    monkeypatch.setattr(domain, "get_file_storage", lambda: storage)
    monkeypatch.setattr(domain.rag_document_repo, "get_by_id", AsyncMock(return_value=doc))
    monkeypatch.setattr(
        domain.knowledge_base_repo,
        "get_by_id",
        AsyncMock(return_value=None if case == "missing_kb" else kb),
    )
    update = AsyncMock(return_value=doc)
    monkeypatch.setattr(domain.rag_document_repo, "update_status", update)
    service = domain.RAGDocumentService(mock_db_session)
    queued = AsyncMock()
    monkeypatch.setattr(service, "_queue_parse", queued)
    if case == "valid":
        assert await service.retry_ingestion(str(doc.id)) is doc
        assert update.await_args is not None
        assert update.await_args.kwargs["ingestion_config"] == kb.ingestion_config
        assert update.await_args.kwargs["expected_attempt"] == 1
        queued.assert_awaited_once()
    else:
        with pytest.raises(NotFoundError if case == "missing_kb" else BadRequestError):
            await service.retry_ingestion(str(doc.id))
        queued.assert_not_awaited()
        update.assert_not_awaited()


@pytest.mark.parametrize(
    "status, snapshot, vector, available",
    [
        (DocumentStatus.STORED, "snapshot", None, True),
        (DocumentStatus.STORED, None, None, False),
        (DocumentStatus.PROCESSING, "snapshot", None, False),
        (DocumentStatus.ERROR, "snapshot", None, False),
        (DocumentStatus.DONE, "snapshot", "vector", True),
    ],
)
def test_parsed_preview_availability_matches_the_content_endpoint(
    status: DocumentStatus, snapshot: str | None, vector: str | None, available: bool
) -> None:
    from app.services.rag_document import _tracked_item

    doc = RAGDocument(
        id=uuid4(),
        collection_name="destination",
        filename="file.txt",
        filetype="txt",
        filesize=1,
        chunk_count=0,
        status=status,
        parsed_content_path=snapshot,
        vector_document_id=vector,
        ingestion_config={},
    )
    assert _tracked_item(doc).has_parsed_content is available
