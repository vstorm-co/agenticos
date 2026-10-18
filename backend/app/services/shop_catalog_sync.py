"""Shop catalog → RAG sync on Agentra (D3 B63)."""

from __future__ import annotations

import logging
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import storefront_shop_cskh as shop_bff
from app.commands.rag import get_rag_services
from app.core.background import spawn_after_commit
from app.core.exceptions import BadRequestError
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.repositories import knowledge_base_repo, rag_document as rag_document_repo
from app.repositories import shop_catalog_sync_settings as settings_repo
from app.schemas.shop_catalog_sync import (
    ShopCatalogSyncItemOut,
    ShopCatalogSyncRunOut,
    ShopCatalogSyncStatusRead,
)
from app.services.knowledge_base import _derive_collection_name
from app.services.rag.ingestion import IngestionService
from app.services.rag.models import IngestionStatus
from app.services.shop_catalog_text import catalog_item_hash, render_catalog_item_text
from app.services.shop_faq_suggestion_utils import is_faq_kb

logger = logging.getLogger(__name__)

SHOP_CATALOG_KB_NAME = "Shop catalog"
CATALOG_SOURCE_PREFIX = "catalog://"
MAX_ITEMS_PER_TENANT = 5000
MANUAL_RUN_COOLDOWN = timedelta(minutes=10)
PAGE_SIZE = 100
_CATALOG_VERSION_KEY = "shop_catalog_version"


def catalog_source_path(item_id: str | UUID) -> str:
    return f"{CATALOG_SOURCE_PREFIX}{item_id}"


def _catalog_version(doc: RAGDocument | None) -> str | None:
    if doc is None or not doc.ingestion_override:
        return None
    raw = doc.ingestion_override.get(_CATALOG_VERSION_KEY)
    return str(raw) if raw else None


async def _get_rag_doc_for_catalog_item(
    db: AsyncSession,
    *,
    kb_id: UUID,
    item_id: str,
) -> RAGDocument | None:
    path = catalog_source_path(item_id)
    result = await db.execute(
        select(RAGDocument).where(
            RAGDocument.knowledge_base_id == kb_id,
            RAGDocument.source_path == path,
        )
    )
    return result.scalar_one_or_none()


async def _list_catalog_rag_docs(db: AsyncSession, *, kb_id: UUID) -> list[RAGDocument]:
    result = await db.execute(
        select(RAGDocument).where(
            RAGDocument.knowledge_base_id == kb_id,
            RAGDocument.source_path.like(f"{CATALOG_SOURCE_PREFIX}%"),
        )
    )
    return list(result.scalars().all())


async def ensure_shop_catalog_kb(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> KnowledgeBase:
    rows = await knowledge_base_repo.list_org_scoped(db, organization_id)
    for row in rows:
        if row.name == SHOP_CATALOG_KB_NAME:
            return row
    if not rows:
        raise BadRequestError(
            message="Organization has no knowledge base template — provision shop org first",
            details={"organization_id": str(organization_id)},
        )
    ref = next((kb for kb in rows if is_faq_kb(kb)), rows[0])
    return await knowledge_base_repo.create(
        db,
        name=SHOP_CATALOG_KB_NAME,
        collection_name=_derive_collection_name(SHOP_CATALOG_KB_NAME),
        scope=KBScope.ORG.value,
        description="Auto-synced product catalog for Shop AI RAG",
        owner_user_id=ref.owner_user_id,
        organization_id=organization_id,
        ingestion_config=dict(ref.ingestion_config or {}),
        embedding_model=ref.embedding_model,
        embedding_dim=ref.embedding_dim,
        embedding_provider=ref.embedding_provider,
        embedding_secret_id=ref.embedding_secret_id,
        embedding_endpoint_id=ref.embedding_endpoint_id,
    )


class ShopCatalogSyncService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_status(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
    ) -> ShopCatalogSyncStatusRead:
        await settings_repo.get_or_create(
            self.db,
            minerp_tenant_id=minerp_tenant_id,
            organization_id=organization_id,
        )
        settings = await settings_repo.get(self.db, minerp_tenant_id)
        assert settings is not None
        kb = await self._find_catalog_kb(organization_id)
        return ShopCatalogSyncStatusRead(
            enabled=settings.enabled,
            last_run_at=settings.last_run_at,
            last_success_at=settings.last_success_at,
            last_item_count=settings.last_item_count,
            last_error=settings.last_error,
            catalog_kb_id=kb.id if kb else None,
        )

    async def set_enabled(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        enabled: bool,
    ) -> ShopCatalogSyncStatusRead:
        await settings_repo.set_enabled(
            self.db,
            minerp_tenant_id=minerp_tenant_id,
            organization_id=organization_id,
            enabled=enabled,
        )
        return await self.get_status(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
        )

    async def sync_item_by_id(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        item_id: UUID,
        action: str = "auto",
    ) -> ShopCatalogSyncItemOut:
        settings = await settings_repo.get_or_create(
            self.db,
            minerp_tenant_id=minerp_tenant_id,
            organization_id=organization_id,
        )
        if not settings.enabled:
            return ShopCatalogSyncItemOut(
                status="skipped",
                item_id=item_id,
                action=action,
                message="Catalog sync is disabled",
            )

        tenant_str = str(minerp_tenant_id)
        if action == "tombstone":
            removed = await self.tombstone_item_by_id(
                organization_id=organization_id,
                item_id=item_id,
            )
            return ShopCatalogSyncItemOut(
                status="done",
                item_id=item_id,
                action="tombstone",
                message="removed" if removed else "not_found",
            )

        try:
            row = await shop_bff.get_catalog_item(tenant_id=tenant_str, item_id=str(item_id))
        except Exception as exc:
            logger.warning("Catalog item fetch failed %s: %s", item_id, exc)
            removed = await self.tombstone_item_by_id(
                organization_id=organization_id,
                item_id=item_id,
            )
            return ShopCatalogSyncItemOut(
                status="done",
                item_id=item_id,
                action="tombstone",
                message="removed_after_fetch_error" if removed else "fetch_error",
            )

        if action == "auto" and not _is_sellable_row(row):
            removed = await self.tombstone_item_by_id(
                organization_id=organization_id,
                item_id=item_id,
            )
            return ShopCatalogSyncItemOut(
                status="done",
                item_id=item_id,
                action="tombstone",
                message="removed_inactive" if removed else "inactive_not_indexed",
            )

        kb = await ensure_shop_catalog_kb(self.db, organization_id=organization_id)
        outcome = await self._sync_item(kb=kb, organization_id=organization_id, item=row)
        return ShopCatalogSyncItemOut(
            status="done",
            item_id=item_id,
            action="upsert",
            message=outcome,
        )

    async def tombstone_item_by_id(
        self,
        *,
        organization_id: UUID,
        item_id: UUID,
    ) -> bool:
        kb = await self._find_catalog_kb(organization_id)
        if kb is None:
            return False
        existing = await _get_rag_doc_for_catalog_item(
            self.db, kb_id=kb.id, item_id=str(item_id)
        )
        if existing is None:
            return False
        ingestion = self._ingestion_for_kb(kb)
        if existing.vector_document_id:
            await ingestion.remove_document(kb.collection_name, existing.vector_document_id)
        await rag_document_repo.delete(self.db, existing.id)
        return True

    async def run(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        manual: bool = False,
    ) -> ShopCatalogSyncRunOut:
        settings = await settings_repo.get_or_create(
            self.db,
            minerp_tenant_id=minerp_tenant_id,
            organization_id=organization_id,
        )
        if not settings.enabled and not manual:
            return ShopCatalogSyncRunOut(status="skipped", message="Catalog sync is disabled")
        if manual and settings.last_manual_run_at:
            elapsed = datetime.now(UTC) - settings.last_manual_run_at
            if elapsed < MANUAL_RUN_COOLDOWN:
                raise BadRequestError(
                    message="Manual sync rate limit — try again later",
                    details={
                        "retry_after_seconds": int((MANUAL_RUN_COOLDOWN - elapsed).total_seconds())
                    },
                )

        kb = await ensure_shop_catalog_kb(self.db, organization_id=organization_id)
        ingestion = self._ingestion_for_kb(kb)
        seen_ids: set[str] = set()
        indexed = 0
        skipped = 0
        errors: list[str] = []
        cursor = 0
        tenant_str = str(minerp_tenant_id)

        try:
            while indexed + skipped < MAX_ITEMS_PER_TENANT:
                payload = await shop_bff.list_catalog_items(
                    tenant_id=tenant_str,
                    cursor=cursor,
                    limit=PAGE_SIZE,
                    active_only=True,
                )
                items = payload.get("items") or []
                if not items and not payload.get("has_more"):
                    break
                for item in items:
                    item_id = str(item.get("id") or "")
                    if not item_id:
                        continue
                    seen_ids.add(item_id)
                    try:
                        outcome = await self._sync_item(
                            kb=kb,
                            organization_id=organization_id,
                            item=item,
                        )
                        if outcome == "indexed":
                            indexed += 1
                        else:
                            skipped += 1
                    except Exception as exc:
                        logger.exception("Catalog item sync failed %s", item_id)
                        errors.append(f"{item_id}: {exc}")
                cursor = int(payload.get("next_cursor") or cursor)
                if not payload.get("has_more"):
                    break

            tombstoned = await self._tombstone_missing(
                ingestion,
                kb=kb,
                seen_ids=seen_ids,
            )
            success = not errors
            await settings_repo.record_run(
                self.db,
                minerp_tenant_id,
                success=success,
                item_count=indexed,
                error="; ".join(errors[:3]) if errors else None,
                manual=manual,
            )
            return ShopCatalogSyncRunOut(
                status="done" if success else "partial",
                indexed=indexed,
                skipped=skipped,
                tombstoned=tombstoned,
                message=f"Indexed {indexed} items, skipped {skipped}, removed {tombstoned}",
                errors=errors[:10],
            )
        except Exception as exc:
            await settings_repo.record_run(
                self.db,
                minerp_tenant_id,
                success=False,
                item_count=0,
                error=str(exc)[:500],
                manual=manual,
            )
            raise

    async def _find_catalog_kb(self, organization_id: UUID) -> KnowledgeBase | None:
        rows = await knowledge_base_repo.list_org_scoped(self.db, organization_id)
        for row in rows:
            if row.name == SHOP_CATALOG_KB_NAME:
                return row
        return None

    def _ingestion_for_kb(self, kb: KnowledgeBase) -> IngestionService:
        processor, vector_store, _, _, _ = get_rag_services()
        return IngestionService(
            processor=processor,
            vector_store=vector_store,
            tenant=kb.vector_tenant,
        )

    async def _sync_item(
        self,
        *,
        kb: KnowledgeBase,
        organization_id: UUID,
        item: dict,
    ) -> str:
        text = render_catalog_item_text(item)
        version = catalog_item_hash(text)
        item_id = str(item["id"])
        existing = await _get_rag_doc_for_catalog_item(
            self.db, kb_id=kb.id, item_id=item_id
        )
        if (
            existing
            and _catalog_version(existing) == version
            and existing.status == DocumentStatus.DONE
            and existing.vector_document_id
        ):
            return "skipped"

        ingestion = self._ingestion_for_kb(kb)
        source_path = catalog_source_path(item_id)
        if existing and existing.vector_document_id:
            await ingestion.remove_document(kb.collection_name, existing.vector_document_id)

        filename = f"catalog-{item_id}.txt"
        if existing is None:
            doc = await rag_document_repo.create(
                self.db,
                collection_name=kb.collection_name,
                filename=filename,
                filesize=len(text.encode("utf-8")),
                filetype="catalog",
                storage_path="",
                source_path=source_path,
                status=DocumentStatus.PROCESSING,
                organization_id=organization_id,
                knowledge_base_id=kb.id,
            )
        else:
            doc = existing
            doc.filesize = len(text.encode("utf-8"))
            doc.status = DocumentStatus.PROCESSING
            doc.error_message = None
            await self.db.flush()

        doc.ingestion_override = {_CATALOG_VERSION_KEY: version}
        await self.db.flush()

        result = await self._ingest_text(
            ingestion,
            text=text,
            collection_name=kb.collection_name,
            source_path=source_path,
            filename=filename,
        )
        if result.status == IngestionStatus.ERROR:
            await rag_document_repo.update_status(
                self.db,
                doc.id,
                status=DocumentStatus.ERROR,
                error_message=result.error_message or result.message,
            )
            raise RuntimeError(result.error_message or result.message or "ingestion failed")

        await rag_document_repo.update_status(
            self.db,
            doc.id,
            status=DocumentStatus.DONE,
            vector_document_id=result.document_id,
            chunk_count=result.chunk_count or 0,
            completed_at=datetime.now(UTC),
            error_message=None,
        )
        return "indexed"

    async def _ingest_text(
        self,
        ingestion: IngestionService,
        *,
        text: str,
        collection_name: str,
        source_path: str,
        filename: str,
    ):
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(text)
            tmp_path = Path(tmp.name)
        try:
            return await ingestion.ingest_file(
                tmp_path,
                collection_name,
                replace=True,
                source_path=source_path,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    async def _tombstone_missing(
        self,
        ingestion: IngestionService,
        *,
        kb: KnowledgeBase,
        seen_ids: set[str],
    ) -> int:
        existing = await _list_catalog_rag_docs(self.db, kb_id=kb.id)
        removed = 0
        for doc in existing:
            if not doc.source_path or not doc.source_path.startswith(CATALOG_SOURCE_PREFIX):
                continue
            item_id = doc.source_path.removeprefix(CATALOG_SOURCE_PREFIX)
            if item_id not in seen_ids:
                if doc.vector_document_id:
                    await ingestion.remove_document(kb.collection_name, doc.vector_document_id)
                await rag_document_repo.delete(self.db, doc.id)
                removed += 1
        return removed


def _is_sellable_row(item: dict) -> bool:
    lifecycle = (item.get("lifecycle_status_code") or "").upper()
    if lifecycle != "ACTIVE":
        return False
    authorized = item.get("authorized_for_sale")
    if authorized is None:
        authorized = item.get("authorized_for_sale_flag")
    return authorized is not False


async def run_nightly_catalog_sync_all_entitled(db: AsyncSession) -> dict[str, int]:
    """Prefect beat: entitled shop_ai tenants with catalog sync enabled (D3 B74)."""
    from app.repositories import tenant_service_entitlement as entitlement_repo
    from app.services.shop_ai_entitlement import SHOP_AI_SERVICE_CODE

    entitled = set(
        await entitlement_repo.list_tenants_with_service(
            db, service_code=SHOP_AI_SERVICE_CODE
        )
    )
    enabled_rows = await settings_repo.list_enabled_settings(db)
    ok = 0
    skipped = 0
    failed = 0
    for row in enabled_rows:
        if entitled and row.minerp_tenant_id not in entitled:
            skipped += 1
            continue
        if not entitled:
            skipped += 1
            continue
        try:
            result = await ShopCatalogSyncService(db).run(
                organization_id=row.organization_id,
                minerp_tenant_id=row.minerp_tenant_id,
                manual=False,
            )
            if result.status == "skipped":
                skipped += 1
            else:
                ok += 1
        except Exception:
            failed += 1
            logger.exception(
                "Nightly catalog sync failed tenant=%s org=%s",
                row.minerp_tenant_id,
                row.organization_id,
            )
    return {"synced": ok, "skipped": skipped, "failed": failed}


def queue_catalog_item_sync_after_commit(
    session: AsyncSession,
    *,
    organization_id: UUID,
    minerp_tenant_id: UUID,
    item_id: UUID,
    action: str,
) -> None:
    from app.worker.tasks.shop_catalog_sync import run_catalog_item_sync_background

    spawn_after_commit(
        session,
        run_catalog_item_sync_background(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            item_id=item_id,
            action=action,
        ),
        name=f"shop_catalog_sync:{item_id}",
    )
