"""RAG sync service."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.sync_log import SyncLog
from app.repositories import sync_log_repo
from app.schemas.rag import RAGSyncLogItem, RAGSyncLogList
from app.worker.tasks.rag_tasks import sync_collection_flow


def _as_item(log: SyncLog) -> RAGSyncLogItem:
    """One sync log as the API reports it.

    Built field by field rather than with ``model_validate``, which raised on
    every row: the schema's ``id`` is a string and the column is a ``UUID``, so
    ``GET /rag/sync/logs`` answered 500 for any organization that had ever
    synced anything.
    """
    return RAGSyncLogItem(
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
        started_at=log.started_at.isoformat(),
        completed_at=log.completed_at.isoformat() if log.completed_at else None,
    )


class RAGSyncService:
    """Service for RAG sync operation management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_sync_logs(
        self,
        *,
        collections: list[str],
        limit: int = 20,
    ) -> RAGSyncLogList:
        """Return up to `limit` sync log entries ordered newest-first.

        ``collections`` is required and has no default: the caller has already
        decided which collections it may report on, and "all of them" must not
        be reachable by omission. The caller also chooses `limit` — no
        server-side cap beyond `limit` is applied.
        """
        logs = await sync_log_repo.get_all(self.db, collections=collections, limit=limit)
        return RAGSyncLogList(items=[_as_item(log) for log in logs], total=len(logs))

    async def get_sync_log(self, sync_id: str) -> SyncLog:
        """Get a sync log by ID.

        Raises:
            NotFoundError: If sync log does not exist.
        """
        log = await sync_log_repo.get_by_id(self.db, UUID(sync_id))
        if not log:
            raise NotFoundError(
                message="Sync log not found",
                details={"sync_id": sync_id},
            )
        return log

    async def create_sync_log(
        self,
        *,
        source: str,
        collection_name: str,
        mode: str,
    ) -> SyncLog:
        """Create a new sync log entry."""
        return await sync_log_repo.create(
            self.db,
            source=source,
            collection_name=collection_name,
            mode=mode,
        )

    async def start_local_sync(
        self,
        *,
        collection_name: str,
        mode: str,
        path: str | None,
    ) -> SyncLog:
        """Persist a sync log and dispatch the local-sync task on the configured backend."""
        sync_log = await self.create_sync_log(
            source="local",
            collection_name=collection_name,
            mode=mode,
        )
        from app.core.background import spawn

        spawn(
            sync_collection_flow(
                sync_log_id=str(sync_log.id),
                source="local",
                collection_name=collection_name,
                mode=mode,
                path=path,
            ),
            name=f"sync-collection-{collection_name}",
        )
        return sync_log

    async def complete_sync(
        self,
        sync_id: str,
        *,
        status: str,
        total_files: int = 0,
        ingested: int = 0,
        updated: int = 0,
        skipped: int = 0,
        failed: int = 0,
        error_message: str | None = None,
    ) -> None:
        """Mark a sync operation as completed (done or error)."""
        log = await self.get_sync_log(sync_id)
        await sync_log_repo.update_status(
            self.db,
            log.id,
            status=status,
            total_files=total_files,
            ingested=ingested,
            updated=updated,
            skipped=skipped,
            failed=failed,
            error_message=error_message,
            completed_at=datetime.now(UTC),
        )

    async def cancel_sync(self, sync_id: str) -> SyncLog:
        """Cancel a running sync operation.

        Raises:
            NotFoundError: If sync log does not exist.
            BadRequestError: If sync is not in 'running' state.
        """
        log = await self.get_sync_log(sync_id)
        if log.status != "running":
            raise BadRequestError(
                message="Sync is not in running state",
                details={"sync_id": sync_id, "current_status": log.status},
            )
        cancelled = await sync_log_repo.update_status(
            self.db,
            log.id,
            status="cancelled",
            completed_at=datetime.now(UTC),
        )
        if cancelled is None:
            raise NotFoundError(message="Sync log not found", details={"sync_id": sync_id})
        return cancelled
