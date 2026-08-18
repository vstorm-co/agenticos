# ruff: noqa: I001
"""Sync source service - org-scoped integration management."""

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.updates import writable
from app.core.config import settings
from app.core.crypto import decrypt_value, encrypt_value, is_encrypted
from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.sync_source import SyncSource
from app.services.rag.connectors import CONNECTOR_REGISTRY
from app.repositories import sync_log as sync_log_repo
from app.repositories import sync_source as sync_source_repo
from app.schemas.rag import RAGSyncLogItem, RAGSyncLogList
from app.schemas.sync_source import (
    ConnectorConfigField,
    ConnectorInfo,
    ConnectorList,
    SyncSourceClone,
    SyncSourceCreate,
    SyncSourceList,
    SyncSourceRead,
    SyncSourceUpdate,
)

_SECRET_MASK = "••••••"


def _secret_fields(connector_type: str) -> set[str]:
    cls = CONNECTOR_REGISTRY.get(connector_type)
    if not cls:
        return set()
    return {name for name, spec in cls.CONFIG_SCHEMA.items() if spec.get("secret")}


def _encrypt_config(config: dict, connector_type: str) -> dict:
    secrets = _secret_fields(connector_type)
    return {
        k: (
            encrypt_value(v, settings.SECRET_KEY)
            if k in secrets and isinstance(v, str) and v and not is_encrypted(v)
            else v
        )
        for k, v in config.items()
    }


def _decrypt_config(config: dict) -> dict:
    return {
        k: (decrypt_value(v, settings.SECRET_KEY) if is_encrypted(v) else v)
        for k, v in config.items()
    }


def _mask_config(config: dict, connector_type: str) -> dict:
    secrets = _secret_fields(connector_type)
    return {
        k: (_SECRET_MASK if k in secrets and isinstance(v, str) and v else v)
        for k, v in config.items()
    }


async def _refuse_an_invalid_config(config: dict, connector_type: str) -> None:
    """Ask the connector whether it would accept this config, before it is stored.

    Every write path asks, so a value the connector refuses cannot be persisted
    by any of them. The alternative is a check that lives only on the sink -
    correct, but it answers in a background sync log rather than to the caller
    who sent the value, and only once somebody triggers a run.

    Whichever fields the connector named travel on as `details["fields"]`, in
    the one shape a form reads (`app/core/field_errors.py`). Flattening them
    into the sentence is what left the wizard with four inputs and a line of
    prose saying one of them was wrong (#897).
    """
    connector_cls = CONNECTOR_REGISTRY.get(connector_type)
    if connector_cls is None:  # pragma: no cover - a stored row names a live connector
        return
    refusal = await connector_cls().validate_config(config)
    if refusal is not None:
        raise BadRequestError(
            message=f"Invalid connector config: {refusal.message}",
            details={"connector_type": connector_type, "fields": refusal.fields},
        )


def _raw_config(source: SyncSource) -> dict:
    c = source.config
    if isinstance(c, dict):
        return c
    if c:
        return json.loads(c)
    return {}


class SyncSourceService:
    """Service for managing sync source configurations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _to_read(self, s: SyncSource) -> SyncSourceRead:
        raw = _raw_config(s)
        return SyncSourceRead(
            id=str(s.id),
            organization_id=str(s.organization_id) if s.organization_id else None,
            name=s.name,
            connector_type=s.connector_type,
            collection_name=s.collection_name,
            config=_mask_config(raw, s.connector_type),
            sync_mode=s.sync_mode,
            schedule_minutes=s.schedule_minutes,
            is_active=s.is_active,
            last_sync_at=s.last_sync_at.isoformat() if s.last_sync_at else None,
            last_sync_status=s.last_sync_status,
            last_error=s.last_error,
            created_at=s.created_at.isoformat() if s.created_at else None,
        )

    @staticmethod
    def decrypt_config_dict(raw: dict) -> dict:
        """Decrypt an encrypted config dict (used by background tasks)."""
        return _decrypt_config(raw)

    async def list_sources(
        self,
        organization_id: UUID | None = None,
        collection_name: str | None = None,
        is_active: bool | None = None,
    ) -> SyncSourceList:
        """List sync sources for an org, optionally filtered by KB collection."""
        sources = await sync_source_repo.get_all(
            self.db,
            organization_id=organization_id,
            collection_name=collection_name,
            is_active=is_active,
        )
        return SyncSourceList(items=[self._to_read(s) for s in sources], total=len(sources))

    async def get_source(self, source_id: str) -> SyncSource:
        """Get a sync source by ID.

        Raises:
            NotFoundError: If sync source does not exist.
        """
        source = await sync_source_repo.get_by_id(self.db, UUID(source_id))
        if not source:
            raise NotFoundError(
                message="Sync source not found",
                details={"source_id": source_id},
            )
        return source

    async def list_logs(self, source_id: UUID, *, limit: int = 20) -> RAGSyncLogList:
        """One source's run history, newest first.

        Both surfaces that show a source's history - a knowledge base's sync row
        and an org integration - read it here rather than each holding its own
        query and its own copy of this mapping. Whoever calls it has already
        decided the caller may see this source: an org integration resolves it
        through `CollectionAccessService`, and a KB route resolves it against the
        base in the path. Scope is not this method's to add, which is why it takes
        an id that has been through one of those.
        """
        logs = await sync_log_repo.get_all(self.db, sync_source_id=source_id, limit=limit)
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

    async def create_source(
        self, data: SyncSourceCreate, organization_id: UUID | None = None
    ) -> SyncSourceRead:
        """Create a new sync source.

        Secret fields are Fernet-encrypted before persisting.
        `collection_name` is optional - omit to create an org-level integration
        not yet linked to a knowledge base.

        Raises:
            BadRequestError: unknown connector or invalid config.
        """
        if data.connector_type not in CONNECTOR_REGISTRY:
            raise BadRequestError(
                message=f"Unknown connector type: {data.connector_type}",
                details={"connector_type": data.connector_type},
            )

        await _refuse_an_invalid_config(data.config, data.connector_type)

        encrypted = _encrypt_config(data.config, data.connector_type)
        source = await sync_source_repo.create(
            self.db,
            name=data.name,
            connector_type=data.connector_type,
            organization_id=organization_id,
            collection_name=data.collection_name,
            config=encrypted,
            sync_mode=data.sync_mode,
            schedule_minutes=data.schedule_minutes,
        )
        return self._to_read(source)

    async def clone_source(
        self, source_id: str, data: SyncSourceClone, organization_id: UUID | None = None
    ) -> SyncSourceRead:
        """Clone an existing integration into a different knowledge base.

        Decrypts credentials from the source, re-encrypts them, and creates
        a new independent SyncSource record targeting `data.collection_name`.
        """
        existing = await self.get_source(source_id)
        raw = _raw_config(existing)
        decrypted = _decrypt_config(raw)
        # A clone copies a config somebody else's row already holds, and rows
        # predating this check exist. Judged again rather than trusted.
        await _refuse_an_invalid_config(decrypted, existing.connector_type)
        re_encrypted = _encrypt_config(decrypted, existing.connector_type)

        source = await sync_source_repo.create(
            self.db,
            name=data.name or f"{existing.name} (copy)",
            connector_type=existing.connector_type,
            organization_id=organization_id or existing.organization_id,
            collection_name=data.collection_name,
            config=re_encrypted,
            sync_mode=existing.sync_mode,
            schedule_minutes=existing.schedule_minutes,
        )
        return self._to_read(source)

    async def update_source(self, source_id: str, data: SyncSourceUpdate) -> SyncSourceRead:
        """Update an existing sync source.

        Masked (••••••) config values are skipped to preserve existing encrypted credentials.

        Raises:
            NotFoundError: If sync source does not exist.
        """
        existing = await self.get_source(source_id)
        updates = writable(data, over=SyncSource)

        if "config" in updates and updates["config"] is not None:
            raw_existing = _raw_config(existing)
            merged: dict = {**raw_existing}
            for k, v in updates["config"].items():
                if isinstance(v, str) and v == _SECRET_MASK:
                    continue
                merged[k] = v
            # The merged config, not the patch: a caller sends one field and the
            # connector judges the whole thing it will actually run with. Asked
            # here as well as on create because `create_source` was the only
            # route that asked, so a value refused at creation could be reached
            # by patching it in afterwards - and the sink check inside the
            # connector then answered an hour later in a sync log rather than to
            # the caller who sent it.
            await _refuse_an_invalid_config(merged, existing.connector_type)
            updates["config"] = _encrypt_config(merged, existing.connector_type)

        source = await sync_source_repo.update(self.db, UUID(source_id), **updates)
        if source is None:
            raise NotFoundError(message="Sync source not found", details={"source_id": source_id})
        return self._to_read(source)

    async def delete_source(self, source_id: str) -> None:
        """Delete a sync source.

        Raises:
            NotFoundError: If sync source does not exist.
        """
        await self.get_source(source_id)
        await sync_source_repo.delete(self.db, UUID(source_id))

    async def trigger_sync(self, source_id: str) -> object:
        """Trigger a manual sync - persists a SyncLog and dispatches the task.

        Raises:
            NotFoundError: If sync source does not exist.
            BadRequestError: If source has no assigned collection.
        """

        source = await self.get_source(source_id)
        if not source.collection_name:
            raise BadRequestError(
                message="Cannot sync a source without an assigned knowledge base collection.",
                details={"source_id": source_id},
            )
        sync_log = await sync_log_repo.create(
            self.db,
            source=source.connector_type,
            collection_name=source.collection_name,
            mode=source.sync_mode,
            sync_source_id=source.id,
        )
        from app.core.background import spawn_after_commit
        from app.worker.tasks.rag_tasks import sync_single_source_flow

        # The flow reads this sync log by id on its own session, so it starts
        # after the commit rather than after this line (#417).
        spawn_after_commit(
            self.db,
            sync_single_source_flow(source_id, str(sync_log.id)),
            name=f"sync-source-{source_id}",
        )
        return sync_log

    async def update_after_sync(
        self,
        source_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        """Update sync source status after a sync operation completes."""
        await sync_source_repo.update_sync_status(
            self.db,
            UUID(source_id),
            last_sync_at=datetime.now(UTC),
            last_sync_status=status,
            last_error=error,
        )

    @staticmethod
    def list_connectors() -> ConnectorList:
        """List available connector types with their config schemas."""
        items = []
        for _connector_type, connector_cls in CONNECTOR_REGISTRY.items():
            schema_fields = {
                field_name: ConnectorConfigField(**field_spec)
                for field_name, field_spec in connector_cls.CONFIG_SCHEMA.items()
            }
            items.append(
                ConnectorInfo(
                    type=connector_cls.CONNECTOR_TYPE,
                    name=connector_cls.DISPLAY_NAME,
                    config_schema=schema_fields,
                    enabled=True,
                )
            )
        return ConnectorList(items=items)
