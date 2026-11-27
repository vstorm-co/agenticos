"""Durable provisioning, teardown and keepalive without fabricated agent runs."""

import logging
from datetime import UTC, datetime

import httpx
from pydantic import TypeAdapter

from app.agents.capabilities.browser_use._endpoint import EndpointError
from app.agents.capabilities.computer_use._backends import ComputerError
from app.core.exceptions import AppException
from app.db.session import get_worker_db_context
from app.repositories import conversation_environment as environments
from app.schemas.project_context import ProjectExecutionTarget
from app.services import conversation_environment_runtime as runtime
from app.services.conversation_environment_policy import current_actor
from app.services.conversation_environments import ConversationEnvironmentService
from app.worker.attempt import current_attempt_number
from app.worker.jobs import ConversationEnvironmentPayload

logger = logging.getLogger(__name__)


async def provision_environment(payload: ConversationEnvironmentPayload) -> None:
    await runtime.start_environment(payload, attempt=current_attempt_number())


async def settle_environment(payload: ConversationEnvironmentPayload, _why: str) -> None:
    async with get_worker_db_context() as db:
        await ConversationEnvironmentService(db).failed(payload)


async def cleanup_environment(payload: ConversationEnvironmentPayload) -> None:
    async with get_worker_db_context() as db:
        resource = await ConversationEnvironmentService(db).cleanup_resource(payload)
    if resource is None:
        return
    await runtime.dispose(resource)
    async with get_worker_db_context() as db:
        await ConversationEnvironmentService(db).cleaned(payload)


async def maintain_environment(payload: ConversationEnvironmentPayload) -> None:
    try:
        async with get_worker_db_context() as db:
            row = await environments.for_worker(db, payload.environment_id)
            if (
                row is None
                or row.organization_id != payload.organization_id
                or row.revision != payload.revision
                or row.state != "ready"
                or row.expires_at <= datetime.now(UTC)
            ):
                return
            if row.user_id is None or row.conversation_id is None:
                await ConversationEnvironmentService(db).expire(row)
                return
            actor = await current_actor(db, payload.organization_id, row.user_id)
            _, resolved, resource = await ConversationEnvironmentService(db).live(
                actor,
                row.conversation_id,
                row.id,
                TypeAdapter(ProjectExecutionTarget).validate_python(row.execution_target),
            )
        async with runtime.open_view(resource, resolved) as view:
            await runtime.picture(view)
    except (AppException, EndpointError, ComputerError, httpx.HTTPError, OSError) as exc:
        logger.warning(
            "conversation_environment_maintenance_failed",
            extra={
                "environment_id": str(payload.environment_id),
                "organization_id": str(payload.organization_id),
                "revision": payload.revision,
                "error_type": type(exc).__name__,
            },
        )
        async with get_worker_db_context() as db:
            row = await environments.for_worker(db, payload.environment_id, for_update=True)
            if row is not None and row.revision == payload.revision:
                await ConversationEnvironmentService(db).expire(row)


async def sweep_environments() -> None:
    async with get_worker_db_context() as db:
        await ConversationEnvironmentService(db).sweep()
