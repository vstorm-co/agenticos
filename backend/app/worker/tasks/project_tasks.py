"""Durable project workspace transfers and cleanup of private failed copies."""

from app.agents.capabilities.sandbox._identity import WorkspaceIdentity, scope_key
from app.core.permissions import AuthContext
from app.db.session import get_worker_db_context
from app.repositories import project_repo
from app.schemas.project import ProjectWorkspaceProgress
from app.services.project_workspace_transfer import ProjectWorkspaceTransferService
from app.services.sandbox_workspace import SandboxWorkspaceService
from app.worker.attempt import current_attempt_number
from app.worker.jobs import (
    MOVE_PROJECT_WORKSPACE,
    MoveProjectWorkspacePayload,
    project_move_generation,
)


async def move_project_workspace(payload: MoveProjectWorkspacePayload) -> ProjectWorkspaceProgress:
    async with get_worker_db_context() as db:
        result = await ProjectWorkspaceTransferService(db).run(
            payload, attempt=current_attempt_number()
        )
    await settle_project_copies(payload, "completed")
    return result


async def settle_project_copies(payload: MoveProjectWorkspacePayload, _why: str) -> None:
    """A dead, cancelled or successful job has no further use for unactivated copies.

    Re-read the active generation under lock: never delete the verified target.
    Cleanup uses teardown authority scoped to the payload tenant, even if the
    requesting member was removed. Durable destroy tombstones survive restarts.
    """
    if payload.target_connection_id is None:
        return
    async with get_worker_db_context() as db:
        project = await project_repo.get(
            db, payload.project_id, organization_id=payload.organization_id, for_update=True
        )
        service = SandboxWorkspaceService(db)
        ctx = AuthContext(user_id=None, organization_id=payload.organization_id, role="owner")
        for attempt in range(1, MOVE_PROJECT_WORKSPACE.max_attempts + 1):
            generation = project_move_generation(payload.transfer_id, attempt)
            if project is not None and project.workspace_generation == generation:
                continue
            identity = WorkspaceIdentity(
                organization_id=payload.organization_id,
                agent_id=None,
                run_id=None,
                project_id=payload.project_id,
                project_workspace_id=generation,
            )
            await service.cleanup_project_copy(
                ctx,
                connection_id=payload.target_connection_id,
                key=scope_key(
                    identity, "project", payload.target_backend, payload.target_connection_id
                ),
            )
