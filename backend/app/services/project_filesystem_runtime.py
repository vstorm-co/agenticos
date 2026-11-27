"""Own mount admission, renewal and release for one run."""

import asyncio
import logging
from uuid import UUID

from app.core.exceptions import ConcurrentChangeError, ExternalServiceError
from app.db.session import get_db_context
from app.schemas.project_filesystem import FsFailure
from app.schemas.project_filesystem_authority import (
    ProjectFilesystemAuthority,
    ProjectFilesystemLeaseRead,
)
from app.services.project_filesystem import ProjectFilesystemService
from app.services.project_filesystem_bindings import ProjectFilesystemBindingService

logger = logging.getLogger(__name__)
RENEW_SECONDS = 30
CLEANUP_SECONDS = 15


class ProjectFilesystemRuntime:
    """Fence failed renewals; release selection on close, allowing later selection."""

    def __init__(self, run_id: UUID, authority: ProjectFilesystemAuthority) -> None:
        self.run_id = run_id
        self.authority = authority
        self._lease: ProjectFilesystemLeaseRead | None = None
        self._binding_id: UUID | None = None
        self._task: asyncio.Task[None] | None = None
        self._failure: BaseException | None = None
        self._lock = asyncio.Lock()
        self._closing: asyncio.Task[Exception | None] | None = None

    def check_health(self) -> None:
        """Refuse further commands when an owned renewal failed."""
        if self._task is not None and self._task.done() and not self._task.cancelled():
            failure = self._task.exception()
            self._failure = failure or RuntimeError(
                "Project filesystem renewal stopped unexpectedly"
            )
        if self._failure is not None:
            raise RuntimeError("The Project filesystem lease is unavailable") from self._failure

    async def directory(self, binding_id: UUID, project_id: UUID, generation: UUID | None) -> str:
        """Reauthorize and commit before exposing the run's directory."""
        async with self._lock:
            if self._closing is not None and not self._closing.done():
                raise RuntimeError("The Project filesystem lease is closing")
            self.check_health()
            if self._lease is not None and (
                self._binding_id != binding_id
                or self._lease.project_id != project_id
                or self._lease.workspace_generation != generation
            ):
                await self._revoke()
            try:
                lease = await self._admit(binding_id, project_id, generation)
            except Exception as exc:
                self._failure = exc
                raise
            if self._task is None:
                self._task = asyncio.create_task(self._renew(), name=f"project-fs-{self.run_id}")
                self._task.add_done_callback(self._finished)
            return lease.path

    async def _admit(
        self, binding_id: UUID, project_id: UUID, generation: UUID | None
    ) -> ProjectFilesystemLeaseRead:
        async with get_db_context() as db:
            from app.services.run_project_workspace import ProjectRunAuthority

            actor, project = await ProjectRunAuthority(
                ctx=self.authority.actor,
                audience=self.authority.audience,
                granted_scopes=self.authority.granted_scopes,
                conversation_project_id=self.authority.conversation_project_id,
            ).project(db, project_id)
            if project.workspace_generation != generation:
                raise ConcurrentChangeError(message="The Project filesystem generation changed")
            if "projects:write" in self.authority.granted_scopes:
                support = await ProjectFilesystemService(db).exclusive_create_support(
                    actor,
                    project_id,
                    generation,
                    writable=True,
                )
                if isinstance(support, FsFailure):
                    raise ExternalServiceError(
                        message="The Project filesystem cannot support a live writable mount",
                        details={"errno": support.errno, "reason": support.message},
                    )
            lease = await ProjectFilesystemBindingService(db).issue_lease(
                binding_id=binding_id,
                project_id=project_id,
                generation=generation,
                run_id=self.run_id,
                authority=self.authority.model_copy(update={"actor": actor}),
            )
            # Retain the id across ambiguous commit cancellation for cleanup.
            self._lease, self._binding_id = lease, binding_id
        return lease

    async def _renew(self) -> None:
        while True:
            await asyncio.sleep(RENEW_SECONDS)
            async with self._lock:
                lease = self._lease
                if lease is None:
                    return
                async with get_db_context() as db:
                    from app.services.run_project_workspace import ProjectRunAuthority

                    _, project = await ProjectRunAuthority(
                        ctx=self.authority.actor,
                        audience=self.authority.audience,
                        granted_scopes=self.authority.granted_scopes,
                        conversation_project_id=self.authority.conversation_project_id,
                    ).project(db, lease.project_id)
                    if project.workspace_generation != lease.workspace_generation:
                        raise ConcurrentChangeError(
                            message="The Project filesystem generation changed"
                        )
                    await ProjectFilesystemBindingService(db).renew(
                        lease_id=lease.id,
                        run_id=self.run_id,
                        organization_id=self.authority.actor.organization_id,
                    )

    def _finished(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        failure = task.exception()
        if failure is not None:
            self._failure = failure
            logger.error(
                "Project filesystem lease renewal failed",
                exc_info=(type(failure), failure, failure.__traceback__),
            )

    async def _revoke(self) -> None:
        lease = self._lease
        if lease is None:
            return
        async with get_db_context() as db:
            await ProjectFilesystemBindingService(db).revoke(
                lease_id=lease.id,
                run_id=self.run_id,
                organization_id=self.authority.actor.organization_id,
            )
        self._lease, self._binding_id = None, None

    async def close(self) -> None:
        """Settle renewal and revoke, preserving cancellation during bounded cleanup."""
        if self._closing is None or self._closing.done():
            self._closing = asyncio.create_task(self._close())
        cleanup = self._closing
        # The owned task returns its error explicitly: Python 3.15 shield reports
        # exceptions from a cancelled shield even when its owner retrieves them.
        try:
            failure = await asyncio.shield(cleanup)
        except asyncio.CancelledError as cancellation:
            failure = await cleanup
            if failure is not None:
                raise BaseExceptionGroup(
                    "Project mount cleanup failed during cancellation", [cancellation, failure]
                ) from None
            raise
        if failure is not None:
            raise failure

    async def _close(self) -> Exception | None:
        try:
            async with asyncio.timeout(CLEANUP_SECONDS):
                # Renewal may own the lock while waiting on the database. Cancel
                # before acquiring it so shutdown can release that transaction.
                task = self._task
                if task is not None:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                async with self._lock:
                    # An admission already in progress may have started renewal
                    # while cleanup waited for its transaction to finish.
                    latest, self._task = self._task, None
                    if latest is not None and latest is not task:
                        latest.cancel()
                        await asyncio.gather(latest, return_exceptions=True)
                    await self._revoke()
        except Exception as failure:
            self._failure = failure
            return failure
        return None
