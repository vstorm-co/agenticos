"""Knowledge originals and parsed snapshots, with explicit unindexed imports."""

from collections.abc import Mapping
from contextlib import aclosing
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from anyio import open_file
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.blocking import run_blocking_settled
from app.core.exceptions import BadRequestError, ConflictError
from app.core.permissions import AuthContext
from app.db.models.rag_document import DocumentStatus
from app.repositories import rag_document_repo
from app.repositories.rag_document import CollectionScope
from app.schemas.resource_bundle import BundleAsset, BundleContentLayer, BundleResource
from app.services.file_storage import BaseFileStorage, get_file_storage
from app.services.knowledge_base import KnowledgeBaseService
from app.services.portability.content import (
    KnowledgeBaseContent,
    KnowledgeDocumentContent,
    PortableIngestionConfig,
)
from app.services.rag.config import RAGSettings
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.parsed_snapshot import (
    MAX_SNAPSHOT_BYTES,
    MAX_SNAPSHOT_CHUNKS,
    MAX_SNAPSHOT_LINE_BYTES,
    ParsedSnapshotChunk,
    snapshot_file_chunks,
)
from app.services.rag.vectorstore import BaseVectorStore, unpooled_vector_store

MAX_KB_DOCUMENTS = 1000

_KB_LAYERS = frozenset({BundleContentLayer.KB_DOCUMENTS, BundleContentLayer.KB_PARSED_TEXT})


def persistent_prefix(operation: UUID, resource: str | None = None) -> str:
    """Only journal UUIDs and validated resource keys form persistent paths."""
    return f"portable-content/{operation}/" + (f"{resource}/" if resource else "")


def count_snapshot_chunks(path: Path) -> int:
    return sum(1 for _ in snapshot_file_chunks(path))


def validate_knowledge_assets(
    resource: BundleResource, assets: tuple[BundleAsset, ...], files: Mapping[str, Path]
) -> int:
    content = KnowledgeBaseContent.model_validate(resource.definition)
    documents = {document.id: document for document in content.documents}
    count = 0
    for asset in assets:
        if asset.layer not in _KB_LAYERS or asset.layer not in resource.included:
            raise BadRequestError(message="This knowledge asset has an unsupported content layer")
        document = documents.get(asset.name)
        if document is None:
            raise BadRequestError(message="A knowledge asset must identify a declared document")
        if asset.layer == BundleContentLayer.KB_DOCUMENTS:
            if document.filesize != asset.size_bytes:
                raise BadRequestError(
                    message="An original does not match its document's recorded size"
                )
        else:
            count += sum(1 for _ in snapshot_file_chunks(files[asset.sha256]))
            if count > MAX_SNAPSHOT_CHUNKS:
                raise BadRequestError(message="Import at most 10,000 parsed chunks per transfer")
    if set(documents) != {asset.name for asset in assets}:
        raise BadRequestError(
            message="Each imported document requires an original or parsed snapshot"
        )
    return count


class KnowledgeTransfer:
    def __init__(
        self,
        db: AsyncSession,
        *,
        storage: BaseFileStorage | None = None,
        vectors: BaseVectorStore | None = None,
    ) -> None:
        self.db = db
        self.storage = storage or get_file_storage()
        self.vectors = vectors

    async def export(
        self,
        ctx: AuthContext,
        resource: BundleResource,
        layers: frozenset[BundleContentLayer],
        directory: Path,
        *,
        asset_budget: int = 2 * 1024**3,
    ) -> tuple[BundleResource, tuple[BundleAsset, ...], dict[str, Path], int]:
        if not layers & _KB_LAYERS:
            return resource, (), {}, 0
        assert resource.source_id is not None
        kb = await KnowledgeBaseService(self.db).get(resource.source_id, ctx=ctx)
        content = KnowledgeBaseContent.model_validate(resource.definition)
        documents: list[KnowledgeDocumentContent] = []
        assets: list[BundleAsset] = []
        files: dict[str, Path] = {}
        cursor: UUID | None = None
        chunks = 0
        remaining = asset_budget
        scanned = 0
        while rows := await rag_document_repo.portable_page(
            self.db, scope=CollectionScope.of(kb), after=cursor
        ):
            for document in rows:
                scanned += 1
                if scanned > MAX_KB_DOCUMENTS:
                    raise BadRequestError(
                        message="Export at most 1,000 knowledge documents at once"
                    )
                selected: list[BundleAsset] = []
                if BundleContentLayer.KB_DOCUMENTS in layers and document.storage_path:
                    path = directory / f"original-{document.id.hex}"
                    size, digest = await self._stage(
                        document.storage_path, path, max_bytes=remaining
                    )
                    if size != document.filesize:
                        raise ConflictError(
                            message="A stored original changed; review this export again"
                        )
                    remaining -= size
                    files[digest] = path
                    selected.append(
                        BundleAsset(
                            resource=resource.key,
                            layer=BundleContentLayer.KB_DOCUMENTS,
                            name=document.id.hex,
                            sha256=digest,
                            size_bytes=size,
                            media_type="application/octet-stream",
                        )
                    )
                if BundleContentLayer.KB_PARSED_TEXT in layers:
                    path = directory / f"parsed-{document.id.hex}"
                    if document.status == DocumentStatus.STORED and document.parsed_content_path:
                        size, digest = await self._stage(
                            document.parsed_content_path,
                            path,
                            max_bytes=min(remaining, MAX_SNAPSHOT_BYTES),
                        )
                        count = await run_blocking_settled(count_snapshot_chunks, path)
                    elif document.status == DocumentStatus.DONE and document.vector_document_id:
                        if self.vectors is None:
                            settings = RAGSettings()
                            self.vectors = unpooled_vector_store(
                                settings, EmbeddingService(settings)
                            )
                        digest_state = sha256()
                        size = count = 0
                        stream = self.vectors.iter_document_chunks(
                            kb.collection_name, document.vector_document_id, kb.vector_scope
                        )
                        async with aclosing(stream), await open_file(path, "wb") as target:
                            async for chunk in stream:
                                line = (
                                    ParsedSnapshotChunk.model_validate(
                                        chunk.model_dump()
                                    ).model_dump_json()
                                    + "\n"
                                ).encode()
                                size += len(line)
                                count += 1
                                if (
                                    len(line) > MAX_SNAPSHOT_LINE_BYTES
                                    or size > min(remaining, MAX_SNAPSHOT_BYTES)
                                    or chunks + count > MAX_SNAPSHOT_CHUNKS
                                ):
                                    raise BadRequestError(
                                        message="This parsed-text export exceeds its chunk or size limit"
                                    )
                                digest_state.update(line)
                                await target.write(line)
                        if count != document.chunk_count:
                            raise ConflictError(
                                message="A document's indexed chunks changed; review this export again"
                            )
                        digest = digest_state.hexdigest()
                    else:
                        count = 0
                        size = -1
                        digest = ""
                    if size >= 0:
                        remaining -= size
                        chunks += count
                        if chunks > MAX_SNAPSHOT_CHUNKS:
                            raise BadRequestError(
                                message="Export at most 10,000 parsed chunks per transfer"
                            )
                        files[digest] = path
                        selected.append(
                            BundleAsset(
                                resource=resource.key,
                                layer=BundleContentLayer.KB_PARSED_TEXT,
                                name=document.id.hex,
                                sha256=digest,
                                size_bytes=size,
                                media_type="application/x-ndjson",
                            )
                        )
                if selected:
                    if not await rag_document_repo.portable_unchanged(self.db, document=document):
                        raise ConflictError(
                            message="A knowledge document changed; review this export again"
                        )
                    # Historical configuration describes the parse. Destination
                    # credentials/profiles are chosen on the KB, not historical chunks.
                    config = PortableIngestionConfig.model_validate(
                        document.ingestion_config
                    ).model_copy(update={"llamaparse_secret_id": None, "ocr_endpoint_id": None})
                    config = config.model_copy(
                        update={
                            "image_description": config.image_description.model_copy(
                                update={"model_profile_id": None}
                            )
                        }
                    )
                    documents.append(
                        KnowledgeDocumentContent(
                            id=document.id.hex,
                            filename=document.filename,
                            filesize=document.filesize,
                            filetype=document.filetype,
                            ingestion_config=config,
                            organizational_unit=document.organizational_unit,
                        )
                    )
                    assets.extend(selected)
            cursor = rows[-1].id
        updated = content.model_copy(update={"documents": tuple(documents)})
        return (
            resource.model_copy(
                update={
                    "definition": updated.model_dump(mode="json"),
                    "included": resource.included | (layers & _KB_LAYERS),
                }
            ),
            tuple(assets),
            files,
            chunks,
        )

    async def _stage(self, stored: str, target: Path, *, max_bytes: int) -> tuple[int, str]:
        digest = sha256()
        size = 0
        stream = await self.storage.open_stream(stored)
        async with aclosing(stream), await open_file(target, "wb") as output:
            async for piece in stream:
                size += len(piece)
                if size > max_bytes:
                    raise BadRequestError(
                        message="The selected assets exceed this transfer's size limit"
                    )
                digest.update(piece)
                await output.write(piece)
        return size, digest.hexdigest()

    async def import_documents(
        self,
        ctx: AuthContext,
        *,
        operation: UUID,
        resource: BundleResource,
        kb_id: UUID,
        assets: tuple[BundleAsset, ...],
        files: Mapping[str, Path],
    ) -> None:
        kb = await KnowledgeBaseService(self.db).get(kb_id, ctx=ctx)
        content = KnowledgeBaseContent.model_validate(resource.definition)
        by_document: dict[str, dict[BundleContentLayer, str]] = {}
        for asset in assets:
            path = f"{persistent_prefix(operation, resource.key)}{asset.name}/{asset.layer}-{asset.sha256}"
            async with await open_file(files[asset.sha256], "rb") as source:
                await self.storage.save_stream_at(path, source.wrapped)
            by_document.setdefault(asset.name, {})[asset.layer] = path
        for document in content.documents:
            paths = by_document[document.id]
            await rag_document_repo.create(
                self.db,
                collection_name=kb.collection_name,
                filename=document.filename,
                filesize=document.filesize,
                filetype=document.filetype,
                storage_path=paths.get(BundleContentLayer.KB_DOCUMENTS, ""),
                parsed_content_path=paths.get(BundleContentLayer.KB_PARSED_TEXT),
                status=DocumentStatus.STORED,
                organization_id=ctx.organization_id,
                knowledge_base_id=kb.id,
                ingestion_config=document.ingestion_config.model_dump(mode="json"),
                organizational_unit=document.organizational_unit,
                initiated_by_user_id=ctx.subject_id,
            )
