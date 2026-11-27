"""A continuously guarded live CDP target, disposed if its owner transport dies."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress

import anyio
from pydantic import TypeAdapter

from app.agents.capabilities.browser_use._page import BrowserTarget, open_page
from app.agents.capabilities.browser_use._route import recheck
from app.core.background import spawn
from app.core.exceptions import AppException
from app.db.session import get_worker_db_context
from app.repositories import agent_run as run_repo
from app.repositories import conversation_environment as environments
from app.schemas.project_context import ProjectExecutionTarget
from app.services import browser_sign_in
from app.services.conversation_environment_policy import BrowserEnvironmentSettings, current_actor
from app.services.conversation_environment_resources import BrowserEnvironmentResource
from app.services.conversation_environments import ConversationEnvironmentService
from app.worker.jobs import ConversationEnvironmentPayload

logger = logging.getLogger(__name__)


async def retain_tab(
    resolved: BrowserEnvironmentSettings,
    payload: ConversationEnvironmentPayload,
    *,
    start_url: str | None,
    keep: Callable[[BrowserTarget], Awaitable[None]],
) -> BrowserTarget:
    """Return only after the exact target is journaled and its egress guard is live.

    The creating CDP connection remains attached while the environment is live.
    Chromium owns disposeOnDetach, so process death or transport loss destroys
    the context instead of leaving page JavaScript running without Fetch policy.
    The row and periodic sweep remain the durable cleanup/status obligation;
    a restarted process never recreates a missing target from URLs or cookies.
    """
    from app.services.conversation_environment_runtime import browser_policy

    ready: asyncio.Future[BrowserTarget] = asyncio.get_running_loop().create_future()

    async def own() -> None:
        target: BrowserTarget | None = None

        async def journal(created: BrowserTarget) -> None:
            nonlocal target
            target = created
            await keep(created)

        try:
            route = None if resolved.route is None else await recheck(resolved.route)
            owner = resolved.authority.ctx.user_id
            sign_ins = (
                []
                if owner is None or (route is not None and route.remote_url is not None)
                else await browser_sign_in.load_for(payload.organization_id, owner)
            )
            async with open_page(
                cdp_url=resolved.cdp_url,
                start_url=start_url,
                policy=browser_policy(resolved),
                route=route,
                sign_ins=sign_ins,
                keep=journal,
            ):
                target = _require_target(target)
                if not ready.done():
                    ready.set_result(target)
                while True:
                    if not await _still_owned(payload, target):
                        break
                    await anyio.sleep(5)
        except asyncio.CancelledError:
            if not ready.done():
                ready.cancel()
            raise
        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)
            else:
                logger.error(
                    "conversation_browser_guard_failed",
                    extra={
                        "environment_id": str(payload.environment_id),
                        "error_type": type(exc).__name__,
                    },
                )
        finally:
            with anyio.move_on_after(15, shield=True):
                try:
                    if ready.done() and not ready.cancelled() and ready.exception() is None:
                        await _ended(payload, ready.result())
                except Exception as cleanup_error:
                    # Chromium has already disposed the context. The durable
                    # sweep will reconcile a database unavailable during exit.
                    logger.error(
                        "conversation_browser_guard_settlement_failed",
                        extra={
                            "environment_id": str(payload.environment_id),
                            "error_type": type(cleanup_error).__name__,
                        },
                    )

    owner_task = spawn(own(), name=f"conversation-browser:{payload.environment_id}")
    try:
        return await ready
    except BaseException:
        owner_task.cancel()
        with anyio.move_on_after(15, shield=True):
            with suppress(asyncio.CancelledError):
                await owner_task
        raise


async def _still_owned(payload: ConversationEnvironmentPayload, target: BrowserTarget) -> bool:
    async with get_worker_db_context() as db:
        service = ConversationEnvironmentService(db)
        row = await environments.for_worker(db, payload.environment_id)
        if (
            row is None
            or row.organization_id != payload.organization_id
            or row.revision != payload.revision
            or row.state not in ("starting", "ready")
        ):
            return False
        if row.state == "starting":
            try:
                if await service.claim(payload, row.provisioning_attempt) is not None:
                    return True
            except AppException:
                return False
            # Provisioning may commit READY while claim resolves project/agent
            # authority. Validate that fresh state instead of ending its target.
            row = await environments.for_worker(db, payload.environment_id)
            if (
                row is None
                or row.organization_id != payload.organization_id
                or row.revision != payload.revision
                or row.state != "ready"
            ):
                return False
        if row.user_id is None or row.conversation_id is None:
            return False
        try:
            actor = await current_actor(db, payload.organization_id, row.user_id)
            _, _, resource = await service.live(
                actor,
                row.conversation_id,
                row.id,
                TypeAdapter(ProjectExecutionTarget).validate_python(row.execution_target),
            )
        except AppException:
            return False
        if row.session_lifetime == "run" and row.source_run_id is not None:
            producer = await run_repo.get_run(
                db, row.source_run_id, organization_id=payload.organization_id
            )
            if producer is None or producer.status != "running":
                return False
        return isinstance(resource, BrowserEnvironmentResource) and target in resource.tabs.values()


async def _ended(payload: ConversationEnvironmentPayload, target: BrowserTarget) -> None:
    async with get_worker_db_context() as db:
        service = ConversationEnvironmentService(db)
        row = await environments.for_worker(db, payload.environment_id, for_update=True)
        if (
            row is None
            or row.vault_organization_id != payload.organization_id
            or row.revision != payload.revision
            or row.state not in ("starting", "ready")
        ):
            return
        if row.resource_ciphertext is not None:
            resource = service.resource(row, payload.organization_id)
            if (
                isinstance(resource, BrowserEnvironmentResource)
                and target not in resource.tabs.values()
            ):
                return
        await service.expire(row)


def _require_target(target: BrowserTarget | None) -> BrowserTarget:
    if target is None:
        raise RuntimeError("The browser did not journal its owned target")
    return target
