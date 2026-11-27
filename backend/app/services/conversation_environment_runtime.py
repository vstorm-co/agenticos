"""Provider I/O for owned environments; authority and journals stay in services."""

import base64
import hashlib
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, replace
from uuid import UUID

import anyio
from pydantic_ai.workspaces import (
    Workspace,
    WorkspaceError,
    WorkspaceRef,
    WorkspaceUnavailableError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.browser_events import BrowserCommand
from app.agents.capabilities.browser_use._loop import PageSession, person_input
from app.agents.capabilities.browser_use._page import (
    BrowserTarget,
    PagePolicy,
    dispose_browser_target,
    open_page,
)
from app.agents.capabilities.browser_use._route import recheck
from app.agents.capabilities.computer_use._actions import Screen
from app.agents.capabilities.computer_use._backends import (
    E2B_DESKTOP_TEMPLATE,
    Computer,
    ComputerError,
    DaemonComputer,
    SandboxComputer,
    open_sandbox_desktop,
)
from app.agents.capabilities.computer_use._live import person_action
from app.agents.capabilities.computer_use._toolset import fit
from app.agents.capabilities.sandbox import WorkspaceIdentity
from app.agents.capabilities.sandbox._e2b import E2BWorkspace
from app.agents.capabilities.sandbox._opensandbox import OpenSandboxWorkspace
from app.agents.capabilities.sandbox._recording import RecordingWorkspace
from app.core.exceptions import ConflictError
from app.db.session import get_worker_db_context
from app.repositories import agent_workspace as workspace_repo
from app.repositories import pending_sandbox_destroy as pending_destroy_repo
from app.services.conversation_environment_policy import (
    BrowserEnvironmentSettings,
    DesktopEnvironmentSettings,
    EnvironmentNotReady,
    EnvironmentSettings,
)
from app.services.conversation_environment_resources import (
    BrowserEnvironmentResource,
    DesktopEnvironmentResource,
    EnvironmentResource,
    StoredBrowserRoute,
)
from app.services.sandbox_workspace import OpenWorkspace, SandboxWorkspaceService, sandbox_config
from app.worker.jobs import ConversationEnvironmentPayload

logger = logging.getLogger(__name__)
ResourceWriter = Callable[[EnvironmentResource, str], Awaitable[bool]]
ProvisionDriver = Callable[[str], AbstractAsyncContextManager[None]]


def resource_key(kind: str, identity: str) -> str:
    return hashlib.sha256(f"{kind}:{identity}".encode()).hexdigest()


def browser_policy(resolved: BrowserEnvironmentSettings) -> PagePolicy:
    return PagePolicy(
        allowed_domains=resolved.config.allowed_domains,
        candidate_cap=resolved.config.candidate_cap,
        preview_width=resolved.config.preview_width,
        allow_blank=True,
    )


@dataclass
class BrowserEnvironmentView:
    page: PageSession


@dataclass
class DesktopEnvironmentView:
    computer: Computer
    width: int
    height: int
    screen: Screen | None = None


type EnvironmentView = BrowserEnvironmentView | DesktopEnvironmentView


@dataclass(frozen=True)
class EnvironmentPicture:
    image: str | None
    url: str | None = None
    title: str | None = None
    navigable: bool = False


async def picture(view: EnvironmentView) -> EnvironmentPicture:
    if isinstance(view, BrowserEnvironmentView):
        url, title = await view.page.location()
        return EnvironmentPicture(await view.page.screenshot(), url, title, True)
    capture = await view.computer.capture()
    image, view.screen = fit(capture, view.width, view.height)
    return EnvironmentPicture("data:image/jpeg;base64," + base64.b64encode(image).decode())


async def perform(view: EnvironmentView, command: BrowserCommand) -> None:
    if isinstance(view, BrowserEnvironmentView):
        await person_input(view.page, command)
        return
    if command.type in ("navigate", "back", "forward", "reload", "resize"):
        raise ComputerError(
            "This desktop does not support browser navigation or viewport resizing."
        )
    if view.screen is None:
        raise ComputerError("Wait for the desktop's first picture before sending input.")
    action = person_action(command, view.screen)
    if action is None:
        raise ComputerError("This desktop command is incomplete or unsupported.")
    await view.computer.perform(action)


async def provision(
    resolved: EnvironmentSettings,
    payload: ConversationEnvironmentPayload,
    store: ResourceWriter,
    drive: ProvisionDriver,
    *,
    attempt: int = 1,
) -> None:
    environment_id = payload.environment_id
    if isinstance(resolved, BrowserEnvironmentSettings):
        from app.services.conversation_environment_browser import retain_tab

        route = resolved.route

        async def keep(target: BrowserTarget) -> None:
            resource = BrowserEnvironmentResource(
                environment_id=environment_id,
                organization_id=resolved.authority.ctx.organization_id,
                cdp_url=resolved.cdp_url,
                route=StoredBrowserRoute.capture(route),
                tabs={"main": target},
            )
            if not await store(
                resource, resource_key("browser", f"{resolved.cdp_url}:{target.context_id}")
            ):
                raise ConflictError(message="This environment was ended while it was starting")

        await retain_tab(resolved, payload, start_url=None, keep=keep)
        return
    await _provision_desktop(resolved, payload, store, drive, attempt=attempt)


def workspace_identity(resolved: DesktopEnvironmentSettings) -> WorkspaceIdentity:
    owner = resolved.authority.ctx.user_id
    return WorkspaceIdentity(
        organization_id=resolved.authority.ctx.organization_id,
        agent_id=resolved.authority.agent.id,
        run_id=resolved.authority.producer_run_id,
        conversation_id=resolved.authority.conversation.id,
        user_id=str(owner) if owner is not None else None,
        project_id=resolved.authority.conversation.project_id,
    )


async def _retain(resource: EnvironmentResource, key: str, store: ResourceWriter) -> None:
    if not await store(resource, key):
        raise ConflictError(message="This environment was ended while it was starting")


def _known_ref(workspace: Workspace) -> WorkspaceRef:
    ref = workspace.ref
    if ref is None:
        raise ComputerError("The desktop did not provide its sandbox identity.")
    return ref


async def _journal_unpublished_sandbox(
    opened: OpenWorkspace, organization_id: UUID, ref: WorkspaceRef
) -> None:
    """Retain cleanup ownership without deleting a possibly published workspace."""
    if opened.connection_id is None or not isinstance(
        opened.sandbox, E2BWorkspace | OpenSandboxWorkspace
    ):
        return
    journaled = False
    with anyio.move_on_after(5, shield=True) as journal_timeout:
        try:
            async with get_worker_db_context() as db:
                await pending_destroy_repo.add(
                    db,
                    organization_id=organization_id,
                    connection_id=opened.connection_id,
                    ref_id=ref.id,
                    scope_key=opened.scope_key,
                )
            journaled = True
        except Exception as error:
            logger.warning(
                "environment_cleanup_journal_failed", extra={"error_type": type(error).__name__}
            )
    if journal_timeout.cancel_called:
        logger.warning("environment_cleanup_journal_timed_out")
    if journaled:
        return
    # No durable receipt was acknowledged. Only this newly created opaque
    # session is safe to destroy; an existing canonical workspace is never here.
    with anyio.move_on_after(10, shield=True) as destroy_timeout:
        try:
            await opened.sandbox.destroy(ref)
        except Exception as error:
            logger.warning(
                "environment_provision_cleanup_failed", extra={"error_type": type(error).__name__}
            )

    if destroy_timeout.cancel_called:
        logger.warning("environment_provision_cleanup_timed_out")


async def _provision_desktop(
    resolved: DesktopEnvironmentSettings,
    payload: ConversationEnvironmentPayload,
    store: ResourceWriter,
    drive: ProvisionDriver,
    *,
    attempt: int,
) -> None:
    environment_id = payload.environment_id
    config, admitted = resolved.config, resolved.authority
    resource = DesktopEnvironmentResource(
        environment_id=environment_id,
        organization_id=admitted.ctx.organization_id,
        backend="sandbox",
        width=config.screen_width,
        height=config.screen_height,
    )
    if config.desktop == "daemon":
        resource.backend, resource.credential, resource.daemon_url = (
            "daemon",
            resolved.credential,
            config.daemon_url,
        )
        computer = DaemonComputer(config.daemon_url, resolved.credential)
        try:
            await computer.capture()
            if not await store(resource, resource_key("daemon", config.daemon_url.rstrip("/"))):
                raise ConflictError(message="This environment was ended while it was starting")
        finally:
            await computer.close()
        return
    if config.desktop == "e2b" or (config.desktop == "auto" and resolved.credential):
        provider = E2BWorkspace(api_key=resolved.credential, template=E2B_DESKTOP_TEMPLATE)
        workspace = Workspace(provider.backend(None))
        try:
            computer = await open_sandbox_desktop(
                workspace, width=config.screen_width, height=config.screen_height
            )
            await computer.capture()
            ref = _known_ref(workspace)
            resource.backend, resource.credential, resource.workspace_ref = (
                "e2b",
                resolved.credential,
                ref,
            )
            resource.workspace_root = await workspace.working_dir()
            await _retain(resource, resource_key("e2b", ref.id), store)
        except BaseException:
            ref = workspace.ref
            if ref is not None:
                resource.backend, resource.credential, resource.workspace_ref = (
                    "e2b",
                    resolved.credential,
                    ref,
                )
                with anyio.move_on_after(15, shield=True):
                    try:
                        try:
                            await store(resource, resource_key("e2b", ref.id))
                        finally:
                            await provider.destroy(ref)
                    except Exception as cleanup_error:
                        logger.warning(
                            "environment_provision_cleanup_failed",
                            extra={"error_type": type(cleanup_error).__name__},
                        )
            raise
        return
    opened: OpenWorkspace | None = None
    initial: WorkspaceRef | None = None
    started = published = orphan_journaled = False
    try:
        async with get_worker_db_context() as db:
            service = SandboxWorkspaceService(db)
            if admitted.execution_target == "project":
                from app.services.project_workspace_guard import project_for_workspace

                project = await project_for_workspace(
                    db, admitted.ctx, admitted.conversation.project_id
                )
                opened = await service.open_project(admitted.ctx, project)
            else:
                sandbox = sandbox_config(admitted.spec)
                if sandbox is None or sandbox.backend != "service":
                    raise EnvironmentNotReady(
                        "workspace_unavailable",
                        "Configure a container-backed sandbox for this agent's desktop.",
                    )
                if sandbox.session_scope == "channel" or (
                    sandbox.session_scope == "run"
                    and (admitted.producer_run_id is None or config.session_lifetime != "run")
                ):
                    raise EnvironmentNotReady(
                        "backend_not_supported",
                        "A persistent desktop needs a conversation, user or agent sandbox scope.",
                    )
                if admitted.producer_run_id is None:
                    opened = await service.open_for_environment(payload, attempt)
                else:
                    opened = await service.open(
                        admitted.spec, ctx=admitted.ctx, identity=workspace_identity(resolved)
                    )
            if opened is None or opened.row_id is None or opened.connection_id is None:
                raise EnvironmentNotReady(
                    "workspace_unavailable", "The desktop has no retained workspace."
                )
            workspace_id, connection_id = opened.row_id, opened.connection_id
            if isinstance(opened.workspace, RecordingWorkspace):
                opened = replace(opened, workspace=opened.workspace.wrapped)
            if opened.connection_fingerprint is None:
                raise EnvironmentNotReady(
                    "environment_changed", "The desktop connection identity is unavailable."
                )
            resource.connection_fingerprint = opened.connection_fingerprint
        initial = opened.workspace.ref
        key = resource_key(
            "workspace", f"{admitted.ctx.organization_id}:{opened.connection_id}:{opened.scope_key}"
        )
        resource.workspace_id, resource.connection_id, resource.workspace_ref = (
            workspace_id,
            connection_id,
            initial,
        )
        # Journal the physical identity before acquiring control, so End cannot race
        # a desktop reset while the provider has not returned a session reference.
        await _retain(resource, key, store)
        async with drive(key):
            started = True
            await open_sandbox_desktop(
                opened.workspace, width=config.screen_width, height=config.screen_height
            )
            ref = opened.workspace.ref
            if ref is None or (initial is not None and ref != initial):
                raise EnvironmentNotReady(
                    "environment_expired", "The original desktop workspace was lost."
                )
            resource.workspace_id, resource.workspace_ref, resource.connection_id = (
                opened.row_id,
                ref,
                opened.connection_id,
            )
            resource.workspace_root = await opened.workspace.working_dir()
            async with get_worker_db_context() as db:
                recorded = await workspace_repo.record_live_session(
                    db,
                    workspace_id=workspace_id,
                    organization_id=admitted.ctx.organization_id,
                    scope_key=opened.scope_key,
                    connection_id=connection_id,
                    initial_session_id=None if initial is None else initial.id,
                    session_id=ref.id,
                )
                # A commit acknowledgement can be lost. Once publication may
                # have succeeded, conservatively preserve the shared workspace.
                published = recorded
                if (
                    not recorded
                    and initial is None
                    and isinstance(opened.sandbox, E2BWorkspace | OpenSandboxWorkspace)
                ):
                    # These providers create a new opaque sandbox, unlike the
                    # named shared sandboxd/Daytona session. Reuse the existing
                    # durable destroy journal if it lost publication.
                    await pending_destroy_repo.add(
                        db,
                        organization_id=admitted.ctx.organization_id,
                        connection_id=connection_id,
                        ref_id=ref.id,
                        scope_key=opened.scope_key,
                    )
            orphan_journaled = (
                not recorded
                and initial is None
                and isinstance(opened.sandbox, E2BWorkspace | OpenSandboxWorkspace)
            )
            if not recorded:
                raise EnvironmentNotReady(
                    "environment_changed",
                    "The selected desktop workspace changed while it was starting.",
                )
            if not await store(
                resource,
                resource_key(
                    "workspace",
                    f"{admitted.ctx.organization_id}:{opened.connection_id}:{opened.scope_key}",
                ),
            ):
                raise ConflictError(message="This environment was ended while it was starting")
    finally:
        if (
            started
            and initial is None
            and not published
            and not orphan_journaled
            and opened is not None
            and opened.workspace.ref is not None
        ):
            await _journal_unpublished_sandbox(
                opened, admitted.ctx.organization_id, opened.workspace.ref
            )
        if opened is not None and opened.close_transport is not None:
            with anyio.move_on_after(15, shield=True):
                await opened.close_transport()


@asynccontextmanager
async def open_view(
    resource: EnvironmentResource,
    resolved: EnvironmentSettings,
) -> AsyncGenerator[EnvironmentView]:
    if isinstance(resource, BrowserEnvironmentResource) and isinstance(
        resolved, BrowserEnvironmentSettings
    ):
        target = resource.tabs.get(resource.active)
        if target is None:
            raise EnvironmentNotReady(
                "environment_expired", "The original browser tab is unavailable."
            )
        route = None if resolved.route is None else await recheck(resolved.route)
        async with open_page(
            cdp_url=resolved.cdp_url,
            start_url=None,
            policy=browser_policy(resolved),
            route=route,
            retained=target,
        ) as page:
            yield BrowserEnvironmentView(page)
        return
    if not isinstance(resource, DesktopEnvironmentResource) or not isinstance(
        resolved, DesktopEnvironmentSettings
    ):
        raise EnvironmentNotReady(
            "environment_expired", "The protected environment kind does not match."
        )
    if resource.backend == "daemon":
        computer = DaemonComputer(resolved.config.daemon_url, resolved.credential)
        try:
            yield DesktopEnvironmentView(computer, resource.width, resource.height)
        finally:
            await computer.close()
        return
    if resource.workspace_ref is None:
        raise EnvironmentNotReady(
            "environment_expired", "The desktop has no retained sandbox identity."
        )
    transport: Callable[[], Awaitable[None]] | None = None
    if resource.backend == "e2b":
        workspace = Workspace(
            E2BWorkspace(api_key=resolved.credential, template=E2B_DESKTOP_TEMPLATE).backend(
                resource.workspace_ref
            )
        )
    else:
        if resource.workspace_id is None or resource.connection_fingerprint is None:
            raise EnvironmentNotReady(
                "environment_expired", "The desktop has no retained workspace."
            )
        async with get_worker_db_context() as db:
            opened = await SandboxWorkspaceService(db).attach_live_environment(
                resolved.authority.ctx,
                spec=resolved.authority.spec,
                identity=workspace_identity(resolved),
                execution_target=resolved.authority.execution_target,
                workspace_id=resource.workspace_id,
                ref=resource.workspace_ref,
                connection_fingerprint=resource.connection_fingerprint,
                environment_id=resource.environment_id,
            )
        workspace, transport = opened.workspace, opened.close_transport
    try:
        try:
            directory = await workspace.working_dir()
        except WorkspaceUnavailableError as exc:
            raise EnvironmentNotReady(
                "environment_expired", "The original desktop workspace is no longer available."
            ) from exc
        except WorkspaceError as exc:
            raise EnvironmentNotReady(
                "connection_unavailable", "The original desktop workspace could not be reached."
            ) from exc
        if resource.workspace_root is None or directory != resource.workspace_root:
            raise EnvironmentNotReady(
                "environment_changed", "The original desktop working directory changed."
            )
        yield DesktopEnvironmentView(SandboxComputer(workspace), resource.width, resource.height)
    finally:
        if transport is not None:
            await transport()


async def dispose(resource: EnvironmentResource) -> None:
    """Destroy owned resources; a shared sandbox and its files are never purged here."""
    if isinstance(resource, BrowserEnvironmentResource):
        route = None if resource.route is None else resource.route.restore()
        seen: set[str] = set()
        for target in resource.tabs.values():
            if target.context_id in seen:
                continue
            await dispose_browser_target(cdp_url=resource.cdp_url, route=route, target=target)
            seen.add(target.context_id)
    elif resource.backend == "e2b" and resource.workspace_ref is not None:
        await E2BWorkspace(api_key=resource.credential, template=E2B_DESKTOP_TEMPLATE).destroy(
            resource.workspace_ref
        )


async def start_environment(payload: ConversationEnvironmentPayload, *, attempt: int) -> None:
    """Provision after admission commits, fencing both durable jobs and real runs."""
    from app.services.conversation_environments import ConversationEnvironmentService

    try:
        async with get_worker_db_context() as db:
            resolved = await ConversationEnvironmentService(db).claim(payload, attempt)
        if resolved is None:
            return

        async def store(resource: EnvironmentResource, key: str) -> bool:
            async with get_worker_db_context() as db:
                return await ConversationEnvironmentService(db).store_resource(
                    payload, attempt, resource, key
                )

        @asynccontextmanager
        async def drive(key: str) -> AsyncGenerator[None]:
            from app.services.conversation_environment_driver import EnvironmentDriver

            async def check(db: AsyncSession) -> None:
                await _check_provision(db, payload, attempt, resolved.fingerprint)

            driver = EnvironmentDriver(key, resolved.authority.ctx, "agent", check)
            try:
                await driver.acquire()
                yield
            finally:
                await driver.close()

        await provision(resolved, payload, store, drive, attempt=attempt)
        async with get_worker_db_context() as db:
            await ConversationEnvironmentService(db).ready(payload, attempt)
    except BaseException as failure:
        reason = (
            failure.refusal.code
            if isinstance(failure, EnvironmentNotReady)
            else "provisioning_failed"
        )
        with anyio.move_on_after(15, shield=True):
            try:
                async with get_worker_db_context() as db:
                    await ConversationEnvironmentService(db).failed(payload, reason=reason)
            except Exception as settlement_failure:
                # The original provider error/cancellation remains authoritative.
                # A durable sweep reconciles this admission after DB recovery.
                logger.error(
                    "environment_provision_settlement_failed",
                    extra={
                        "environment_id": str(payload.environment_id),
                        "error_type": type(settlement_failure).__name__,
                    },
                )
        raise


async def _check_provision(
    db: AsyncSession, payload: ConversationEnvironmentPayload, attempt: int, fingerprint: str
) -> None:
    from app.services.conversation_environments import ConversationEnvironmentService

    current = await ConversationEnvironmentService(db).claim(payload, attempt)
    if current is None or current.fingerprint != fingerprint:
        raise ConflictError(message="The environment provisioning lease is no longer valid")
