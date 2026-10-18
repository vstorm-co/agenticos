"""Qdrant maintenance commands (collection rename / copy / re-ingest)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from app.commands import command, error, info, success, warning
from app.services.rag.qdrant_client import create_qdrant_client
from app.commands.rag import get_rag_services
from app.core.config import settings
from app.db.session import get_db_context
from app.repositories import knowledge_base_repo, rag_document_repo
from app.services.file_storage import get_file_storage
from app.services.ingestion_config import IngestionConfig, IngestionConfigService
from app.services.rag.ingestion import IngestionService
from app.services.rag.models import IngestionStatus


def _client() -> QdrantClient:
    return create_qdrant_client(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY or None,
    )


def _copy_collection_sync(
    client: QdrantClient,
    *,
    source: str,
    dest: str,
    batch_size: int,
    delete_source: bool,
) -> int:
    if client.collection_exists(dest):
        count = int(client.count(dest, exact=False).count or 0)
        raise click.ClickException(
            f"destination collection {dest!r} already exists (~{count} points); "
            "refuse to overwrite"
        )
    if not client.collection_exists(source):
        raise click.ClickException(f"source collection {source!r} does not exist")

    src = client.get_collection(source)
    vectors = src.config.params.vectors  # type: ignore[union-attr]
    client.create_collection(collection_name=dest, vectors_config=vectors)

    total = 0
    offset = None
    while True:
        records, offset = client.scroll(
            collection_name=source,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not records:
            break
        points = [
            PointStruct(id=record.id, vector=record.vector, payload=record.payload or {})
            for record in records
        ]
        client.upsert(collection_name=dest, points=points)
        total += len(points)
        if offset is None:
            break

    if delete_source:
        client.delete_collection(source)
    return total


@command(
    "rag-qdrant-rename-collection",
    help="Copy a Qdrant physical collection to a new name (e.g. agenticos_rag → agentra_rag)",
)
@click.option(
    "--from",
    "source",
    default="agenticos_rag",
    show_default=True,
    help="Existing physical collection name",
)
@click.option(
    "--to",
    "dest",
    default="agentra_rag",
    show_default=True,
    help="New physical collection name",
)
@click.option("--batch-size", default=256, show_default=True, type=int)
@click.option(
    "--delete-source/--keep-source",
    default=False,
    help="Drop the source collection after a successful copy",
)
@click.option("--dry-run", is_flag=True, help="Only report what would happen")
def rag_qdrant_rename_collection(
    source: str,
    dest: str,
    batch_size: int,
    delete_source: bool,
    dry_run: bool,
) -> None:
    """Copy points from one physical Qdrant collection to another."""
    if settings.VECTOR_STORE != "qdrant":
        warning(
            f"VECTOR_STORE is {settings.VECTOR_STORE!r}; this command only touches Qdrant "
            f"at {settings.QDRANT_URL}"
        )

    if source == dest:
        error("source and destination must differ")
        return

    client = _client()
    dest_exists = client.collection_exists(dest)
    src_exists = client.collection_exists(source)

    if dest_exists:
        count = int(client.count(dest, exact=False).count or 0)
        success(f"OK — {dest!r} already exists (~{count} points); no copy needed")
        return

    if not src_exists:
        info(f"Source {source!r} not found — nothing to copy (app will create {dest!r} on ingest)")
        return

    src_count = int(client.count(source, exact=False).count or 0)
    if dry_run:
        info(
            f"Would copy ~{src_count} point(s) from {source!r} → {dest!r} "
            f"(delete_source={delete_source})"
        )
        return

    info(f"Copying ~{src_count} point(s) from {source!r} → {dest!r} …")
    total = _copy_collection_sync(
        client,
        source=source,
        dest=dest,
        batch_size=batch_size,
        delete_source=delete_source,
    )
    success(f"Copied {total} point(s) into {dest!r}")
    if delete_source:
        success(f"Dropped source collection {source!r}")


async def _migrate_to_qdrant_async(
    *,
    collection: str | None,
    dry_run: bool,
) -> None:
    storage = get_file_storage()
    async with get_db_context() as db:
        docs = await rag_document_repo.list_completed_with_storage(db, collection_name=collection)

    if not docs:
        info("No completed documents with stored files found.")
        return

    info(
        f"Found {len(docs)} document(s) to migrate"
        + (f" in collection {collection!r}" if collection else "")
        + (" (dry-run)" if dry_run else "")
        + "."
    )

    _, vector_store, _default_processor, _, _default_ingestion = get_rag_services()
    ok = skipped = failed = 0

    for doc in docs:
        file_path = storage.get_full_path(doc.storage_path or "")
        if not file_path:
            skipped += 1
            warning(f"  skip {doc.filename}: file missing on disk")
            continue

        if dry_run:
            click.echo(f"  would migrate: {doc.filename} → {doc.collection_name}")
            ok += 1
            continue

        async with get_db_context() as db:
            config = IngestionConfig.model_validate(doc.ingestion_config or {})
            processor = await IngestionConfigService(db).build_processor(
                doc.organization_id,
                config,
            )
            kb = (
                await knowledge_base_repo.get_by_id(db, doc.knowledge_base_id)
                if doc.knowledge_base_id is not None
                else None
            )
            tenant = kb.vector_tenant if kb is not None else None

        ingester = IngestionService(
            processor=processor,
            vector_store=vector_store,
            tenant=tenant,
        )
        result = await ingester.ingest_file(
            filepath=Path(file_path),
            collection_name=doc.collection_name,
            replace=True,
            source_path=doc.filename or Path(file_path).name,
        )
        if result.status == IngestionStatus.DONE:
            ok += 1
            success(f"  {doc.filename}: {result.chunk_count} chunks")
        else:
            failed += 1
            error(f"  {doc.filename}: {result.error_message or result.message}")

    click.echo()
    success(f"Migration complete: {ok} ok, {skipped} skipped, {failed} failed")


@command(
    "rag-migrate-qdrant",
    help="Re-ingest completed RAG documents into the active vector store (Qdrant cutover)",
)
@click.option(
    "--collection",
    "-c",
    default=None,
    help="Limit to one logical collection (default: all completed docs)",
)
@click.option("--dry-run", is_flag=True, help="List documents without re-ingesting")
def rag_migrate_qdrant(collection: str | None, dry_run: bool) -> None:
    """
    pgvector → Qdrant: re-run ingestion for completed documents with stored files.

    Runbook:
      1. Pause RAG workers (or drain queue).
      2. Set VECTOR_STORE=qdrant and QDRANT_URL in .env.
      3. uv run python -m cli.commands cmd rag-migrate-qdrant [--dry-run]
      4. Smoke: cmd rag-search against a KB.
    """
    if settings.VECTOR_STORE != "qdrant" and not dry_run:
        warning("VECTOR_STORE is not 'qdrant' — set it before running migration.")
    asyncio.run(_migrate_to_qdrant_async(collection=collection, dry_run=dry_run))
