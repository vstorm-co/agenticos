"""Pass an admitted Workflow delivery to the memory ledger."""

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.db.session import get_worker_db_context
from app.services.memory.workflow import (
    MemoryObservationConfig,
    MemoryObservationOutput,
    record_observation,
    require_editor,
)
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    try:
        require_editor(ctx)
    except AuthorizationError as error:
        return [("object_key", error.message)]
    return []


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, MemoryObservationConfig):
        return Failed(
            error=WorkflowError(code="MEMORY_CONFIG", message="Configure the memory object")
        )
    current = context.current()
    try:
        async with get_worker_db_context() as db:
            result = await record_observation(
                db, auth=current.auth, run_id=current.workflow_run_id, config=config
            )
    except (BadRequestError, AuthorizationError) as error:
        return Failed(error=WorkflowError(code="MEMORY_OBSERVATION_REFUSED", message=error.message))
    return Completed[MemoryObservationOutput](output=result)
