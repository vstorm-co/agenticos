"""Lazy private-web-chat adapters adopting the exact app-owned live resource."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import anyio
from pydantic_ai.workspaces import Workspace
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.browser_events import OwnedEnvironmentView
from app.agents.browser_sign_ins import SignIn
from app.agents.capabilities.browser_use._elements import Element, Snapshot
from app.agents.capabilities.browser_use._loop import PageSession
from app.agents.capabilities.browser_use._page import BrowserTarget, PagePolicy, open_page
from app.agents.capabilities.browser_use._route import BrowserRoute
from app.agents.capabilities.browser_use._toolset import RetainedBrowser
from app.agents.capabilities.computer_use._backends import (
    Capture,
    Computer,
    ComputerError,
    ComputerFactory,
    ComputerFactoryDecorator,
    NativeAction,
)
from app.agents.capabilities.computer_use._desktop_apps import App
from app.agents.capabilities.sandbox import WorkspaceIdentity
from app.core.exceptions import ConflictError
from app.core.permissions import AuthContext
from app.db.models.conversation_environment import ConversationEnvironment
from app.db.session import get_db_context
from app.repositories import conversation_environment as environments
from app.schemas.conversation_environment import (
    ConversationEnvironmentKind,
    ConversationEnvironmentStart,
)
from app.schemas.project_context import ProjectExecutionTarget
from app.services import conversation_environment_runtime as runtime
from app.services.conversation_environment_driver import EnvironmentDriver
from app.services.conversation_environment_policy import (
    BrowserEnvironmentSettings,
    DesktopEnvironmentSettings,
    EnvironmentNotReady,
    EnvironmentSettings,
    authority,
    legacy_run_desktop,
    require_environment_run,
    settings_for,
)
from app.services.conversation_environment_resources import (
    BrowserEnvironmentResource,
    EnvironmentResource,
)
from app.services.conversation_environments import ConversationEnvironmentService, personal_owner
from app.services.run_project_workspace import RunProjectWorkspace
from app.services.sandbox_workspace import OpenWorkspace, SandboxWorkspaceService
from app.worker.jobs import ConversationEnvironmentPayload

if TYPE_CHECKING:
    from app.services.conversation_environment_delegates import SharedDesktopWorkspace


class AgentEnvironment:
    """One real run's lazy driver, never a synthetic admission or a URL checkpoint."""

    def __init__(
        self,
        ctx: AuthContext,
        *,
        conversation_id: UUID,
        agent_id: UUID,
        version_id: UUID,
        run_id: UUID,
        target: ProjectExecutionTarget,
        kind: ConversationEnvironmentKind,
        workspace: SharedDesktopWorkspace | None = None,
    ) -> None:
        self.ctx = ctx
        self.conversation_id = conversation_id
        self.agent_id = agent_id
        self.version_id = version_id
        self.run_id = run_id
        self.target = target
        self.kind = kind
        self.workspace = workspace
        self._routing_workspace: RunProjectWorkspace | None = None
        self._opened_workspace: OpenWorkspace | None = None
        self.environment_id: UUID | None = None
        self.driver: EnvironmentDriver | None = None
        self._lock = asyncio.Lock()
        self._fallback = False
        self._closed = False

    async def acquire(self) -> bool:
        async with self._lock:
            if self._closed:
                raise ConflictError(message="This run's environment adapter is closed")
            if self.driver is not None:
                await self.driver.require()
                return True
            if self._fallback:
                return False
            payload: ConversationEnvironmentPayload | None = None
            checked: DesktopEnvironmentSettings | None = None
            async with get_db_context() as db:
                service = ConversationEnvironmentService(db)
                if self.kind == "desktop":
                    admitted = await authority(
                        db,
                        self.ctx,
                        conversation_id=self.conversation_id,
                        agent_id=self.agent_id,
                        execution_target=self.target,
                    )
                    if admitted.version_id != self.version_id:
                        raise EnvironmentNotReady(
                            "environment_changed",
                            "This run uses a different published agent version.",
                        )
                    if await legacy_run_desktop(db, admitted):
                        self._fallback = True
                        return False
                    if (
                        self.workspace is not None
                        or self._routing_workspace is not None
                        or self._opened_workspace is not None
                    ):
                        configured = await settings_for(db, admitted, "desktop")
                        if isinstance(
                            configured, DesktopEnvironmentSettings
                        ) and await self._check_executor(db, configured):
                            checked = configured
                state = await service.read(
                    self.ctx, self.conversation_id, self.agent_id, self.kind, self.target
                )
                if (
                    self.kind == "browser"
                    and state.session_lifetime == "run"
                    and state.state != "ready"
                ):
                    self._fallback = True
                    return False
                if state.refusal is not None and state.refusal.code not in (
                    "environment_expired",
                    "environment_changed",
                    "provisioning_failed",
                ):
                    raise EnvironmentNotReady(state.refusal.code, state.refusal.message)
                if state.state != "ready":
                    state = await service.ensure(
                        self.ctx,
                        self.conversation_id,
                        self.kind,
                        ConversationEnvironmentStart(
                            agent_id=self.agent_id, project_execution_target=self.target
                        ),
                        producer_run_id=self.run_id,
                    )
                    if state.id is None:
                        raise EnvironmentNotReady(
                            "provisioning_failed", "The environment could not be admitted."
                        )
                    row = await environments.for_worker(db, state.id)
                    if row is None:
                        raise EnvironmentNotReady(
                            "environment_expired", "The environment admission was lost."
                        )
                    if row.source_run_id != self.run_id:
                        raise ConflictError(
                            message="The environment is still starting. Wait until it is ready."
                        )
                    payload = service.payload(row)
                if checked is not None and state.id is not None:
                    current = await environments.for_worker(db, state.id)
                    if current is None or current.fingerprint != checked.fingerprint:
                        raise EnvironmentNotReady(
                            "environment_changed", "The admitted desktop executor changed."
                        )
                self.environment_id = state.id
            if payload is not None:
                # A real RUNNING row already exists. Provider effects happen only
                # on the first actual tool use, after its admission was committed.
                await runtime.start_environment(payload, attempt=1)
            async with get_db_context() as db:
                row, _, _ = await self.live(db)
                if row.resource_key is None:
                    raise EnvironmentNotReady(
                        "environment_expired", "The environment has no physical resource."
                    )
                key = row.resource_key
            driver = EnvironmentDriver(key, self.ctx, "agent", self._check, on_acquired=self._adopt)
            try:
                await driver.acquire()
            except BaseException:
                await driver.close()
                raise
            self.driver = driver
            return True

    async def _check_executor(
        self, db: AsyncSession, configured: DesktopEnvironmentSettings
    ) -> bool:
        """Bind sandbox adoption to captured physical identity, never a fresh replacement."""
        if configured.connection_fingerprint is None:
            return False
        routing = (
            None if self._routing_workspace is None else self._routing_workspace.desktop_selection()
        )
        if routing is not None and routing.target != self.target:
            raise EnvironmentNotReady(
                "environment_changed", "The desktop execution target changed."
            )
        captured = self.workspace
        opened = self._opened_workspace if routing is None else routing.opened
        if opened is not None:
            if opened.connection_id is None or opened.connection_fingerprint is None:
                raise EnvironmentNotReady(
                    "environment_changed", "The original desktop executor has no captured identity."
                )
            from app.services.conversation_environment_delegates import SharedDesktopWorkspace

            captured = SharedDesktopWorkspace(
                opened.connection_id,
                opened.scope_key,
                opened.connection_fingerprint,
                self.target,
                None if routing is None else routing.project_id,
            )
        if captured is None:
            return False
        admitted = configured.authority
        service = SandboxWorkspaceService(db)
        selected = await service.resolve_live_execution(
            admitted.ctx,
            spec=admitted.spec,
            identity=WorkspaceIdentity(
                organization_id=admitted.ctx.organization_id,
                agent_id=self.agent_id,
                run_id=self.run_id,
                conversation_id=self.conversation_id,
                user_id=str(admitted.ctx.user_id),
                project_id=admitted.conversation.project_id,
            ),
            execution_target=self.target,
            selected_project_id=None if routing is None else routing.project_id,
            selected_generation=None if routing is None else routing.project_generation,
        )
        if (
            captured.execution_target != self.target
            or captured.connection_fingerprint != configured.connection_fingerprint
            or captured.connection_id != selected.resolved.row.id
            or captured.scope_key != selected.key
            or service.environment_connection_fingerprint(selected.resolved)
            != configured.connection_fingerprint
        ):
            raise EnvironmentNotReady(
                "environment_changed", "The original desktop executor changed."
            )
        return True

    async def live(
        self, db: AsyncSession
    ) -> tuple[ConversationEnvironment, EnvironmentSettings, EnvironmentResource]:
        if self.environment_id is None:
            raise EnvironmentNotReady("environment_expired", "This run has no live environment.")
        result = await ConversationEnvironmentService(db).live(
            self.ctx, self.conversation_id, self.environment_id, self.target, lock=True, touch=True
        )
        if result[1].authority.version_id != self.version_id:
            raise EnvironmentNotReady(
                "environment_changed", "This run uses a different published agent version."
            )
        return result

    async def _check(self, db: AsyncSession) -> None:
        await self.live(db)
        await self._require_run(db)

    async def _adopt(self, db: AsyncSession) -> None:
        """Bind real use only after the physical claim, in that same transaction."""
        row, _, _ = await self.live(db)
        await self._require_run(db)
        if row.session_lifetime == "run":
            row.source_run_id = self.run_id
            await db.flush()

    async def _require_run(self, db: AsyncSession) -> None:
        await require_environment_run(
            db,
            self.ctx,
            run_id=self.run_id,
            conversation_id=self.conversation_id,
            agent_id=self.agent_id,
            version_id=self.version_id,
        )

    async def load(self) -> tuple[EnvironmentSettings, EnvironmentResource]:
        if self.driver is None:
            raise ConflictError(message="The agent does not hold the environment driver")
        await self.driver.require()
        async with get_db_context() as db:
            _, settings, resource = await self.live(db)
        return settings, resource

    async def store(self, resource: EnvironmentResource) -> None:
        if self.driver is None:
            raise ConflictError(message="The agent does not hold the environment driver")
        await self.driver.require()
        async with get_db_context() as db:
            row, _, _ = await self.live(db)
            held = (
                None
                if row.resource_key is None
                else await environments.driver(db, row.resource_key)
            )
            if (
                held is None
                or held.lease_token != self.driver.token
                or held.lease_until <= datetime.now(UTC)
            ):
                raise ConflictError(message="The environment driver was lost")
            await ConversationEnvironmentService(db).replace_resource(row, resource)

    async def finish(self) -> None:
        with anyio.move_on_after(20, shield=True):
            async with self._lock:
                if self._closed:
                    return
                self._closed = True
                if self.driver is not None:
                    await self.driver.close()
                if self.environment_id is not None:
                    async with get_db_context() as db:
                        row = await environments.owned(
                            db,
                            self.environment_id,
                            organization_id=self.ctx.organization_id,
                            user_id=personal_owner(self.ctx),
                            conversation_id=self.conversation_id,
                            for_update=True,
                        )
                        cleanup: (
                            tuple[ConversationEnvironmentPayload, EnvironmentResource] | None
                        ) = None
                        if row is not None and row.session_lifetime == "run":
                            service = ConversationEnvironmentService(db)
                            resource = (
                                service.resource(row, self.ctx.organization_id)
                                if row.resource_ciphertext is not None
                                else None
                            )
                            await service.expire(row)
                            if resource is not None:
                                cleanup = service.payload(row), resource
                    if cleanup is not None:
                        payload, resource = cleanup
                        await runtime.dispose(resource)
                        async with get_db_context() as db:
                            await ConversationEnvironmentService(db).cleaned(payload)

    def browser(self) -> RetainedBrowser:
        return RetainedBrowser(self.page, self.tabs, self.select, self.close_tab, self.finish)

    async def tabs(self) -> tuple[tuple[str, ...], str] | None:
        if not await self.acquire():
            return None
        _, resource = await self.load()
        if not isinstance(resource, BrowserEnvironmentResource):
            raise EnvironmentNotReady("environment_changed", "The browser resource changed kind.")
        return tuple(resource.tabs), resource.active

    async def select(self, tab_id: str) -> None:
        if self._fallback:
            return
        _, resource = await self.load()
        if not isinstance(resource, BrowserEnvironmentResource) or tab_id not in resource.tabs:
            raise EnvironmentNotReady(
                "environment_changed", "The selected browser tab is unavailable."
            )
        resource.active = tab_id
        await self.store(resource)

    async def close_tab(self, tab_id: str) -> None:
        if self._fallback:
            return
        _, resource = await self.load()
        if not isinstance(resource, BrowserEnvironmentResource):
            raise EnvironmentNotReady("environment_changed", "The browser resource changed kind.")
        target = resource.tabs.get(tab_id)
        if target is None:
            return
        # Keep the target journaled until disposal succeeds, so cancellation or
        # transport failure leaves durable cleanup rather than an orphan.
        await runtime.dispose(resource.model_copy(update={"tabs": {tab_id: target}}))
        del resource.tabs[tab_id]
        if resource.active == tab_id:
            resource.active = next(reversed(resource.tabs), "main")
        await self.store(resource)

    @asynccontextmanager
    async def page(
        self,
        *,
        cdp_url: str,
        start_url: str | None,
        policy: PagePolicy,
        sign_ins: Sequence[SignIn],
        route: BrowserRoute | None,
        retained_tab_id: str,
    ) -> AsyncGenerator[PageSession]:
        if not await self.acquire():
            async with open_page(
                cdp_url=cdp_url, start_url=start_url, policy=policy, sign_ins=sign_ins, route=route
            ) as page:
                yield page
            return
        resolved, resource = await self.load()
        if not isinstance(resolved, BrowserEnvironmentSettings) or not isinstance(
            resource, BrowserEnvironmentResource
        ):
            raise EnvironmentNotReady("environment_changed", "The browser resource changed kind.")
        target = resource.tabs.get(retained_tab_id)

        async def keep(created: BrowserTarget) -> None:
            if len(resource.tabs) >= 8:
                raise ConflictError(message="Eight browser tabs are already open")
            resource.tabs[retained_tab_id] = created
            resource.active = retained_tab_id
            await self.store(resource)

        if target is None:
            from app.services.conversation_environment_browser import retain_tab

            async with get_db_context() as db:
                row, _, _ = await self.live(db)
                payload = ConversationEnvironmentService(db).payload(row)
            target = await retain_tab(resolved, payload, start_url=start_url, keep=keep)
        async with open_page(
            cdp_url=resource.cdp_url,
            start_url=None,
            policy=runtime.browser_policy(resolved),
            route=None if resource.route is None else resource.route.restore(),
            retained=target,
        ) as page:
            if self.driver is None:
                raise ConflictError(message="The browser driver was released")
            yield DrivenPage(page, self.driver, resource.environment_id)

    async def project_directory(
        self,
        binding_id: UUID,
        project_id: UUID,
        generation: UUID | None,
        opened: OpenWorkspace | None = None,
    ) -> str:
        """Use the GUI's stable Project path from the first actual tool operation."""
        from app.services.conversation_environment_project_files import directory

        self._opened_workspace = opened
        async with get_db_context() as db:
            admitted = await authority(
                db,
                self.ctx,
                conversation_id=self.conversation_id,
                agent_id=self.agent_id,
                execution_target=self.target,
            )
            if (
                admitted.execution_target != "agent"
                or admitted.project is None
                or admitted.project.id != project_id
                or admitted.project.workspace_generation != generation
            ):
                raise EnvironmentNotReady(
                    "environment_changed",
                    "The retained desktop uses a different Project selection.",
                )
        if not await self.acquire() or self.environment_id is None:
            raise EnvironmentNotReady(
                "workspace_unavailable", "No retained desktop Project mount is available."
            )
        async with get_db_context() as db:
            return await directory(
                db,
                ctx=self.ctx,
                environment_id=self.environment_id,
                binding_id=binding_id,
                project_id=project_id,
                generation=generation,
            )

    def desktop(self) -> ComputerFactoryDecorator:
        return ComputerFactoryDecorator(self.wrap_computer)

    def wrap_computer(self, fallback: ComputerFactory) -> ComputerFactory:
        async def open_computer(workspace: Workspace) -> Computer:
            if isinstance(workspace, RunProjectWorkspace):
                self._routing_workspace = workspace
            if not await self.acquire():
                return await fallback(workspace)
            stack = AsyncExitStack()
            try:
                resolved, resource = await self.load()
                view = await stack.enter_async_context(runtime.open_view(resource, resolved))
                return DrivenComputer(_desktop_computer(view), self, stack, resource.environment_id)
            except BaseException:
                await stack.aclose()
                await self.finish()
                raise

        return open_computer


class DrivenComputer(OwnedEnvironmentView):
    """Fence every read and input; close detaches transport, then releases the driver."""

    def __init__(
        self,
        wrapped: Computer,
        owner: AgentEnvironment,
        stack: AsyncExitStack,
        environment_id: UUID,
    ) -> None:
        super().__init__(environment_id)
        self.wrapped, self.owner, self.stack = wrapped, owner, stack
        self.label = wrapped.label

    async def _require(self) -> None:
        if self.owner.driver is None:
            raise ComputerError("The desktop driver was released")
        await self.owner.driver.require()

    async def capture(self) -> Capture:
        await self._require()
        return await self.wrapped.capture()

    async def perform(self, action: NativeAction) -> None:
        await self._require()
        await self.wrapped.perform(action)

    async def apps(self) -> list[App]:
        await self._require()
        return await self.wrapped.apps()

    async def close(self) -> None:
        try:
            await self.stack.aclose()
        finally:
            await self.owner.finish()


class DrivenPage(OwnedEnvironmentView):
    """Typed page adapter checking the physical driver before every operation."""

    def __init__(
        self, wrapped: PageSession, driver: EnvironmentDriver, environment_id: UUID
    ) -> None:
        super().__init__(environment_id)
        self.wrapped, self.driver = wrapped, driver
        self.native_id = wrapped.native_id

    @property
    def streaming(self) -> bool:
        return self.wrapped.streaming

    @asynccontextmanager
    async def stream(self, deliver: Callable[[str], Awaitable[None]]) -> AsyncGenerator[None]:
        await self.driver.require()
        async with self.wrapped.stream(deliver):
            yield

    async def snapshot(self) -> Snapshot:
        await self.driver.require()
        return await self.wrapped.snapshot()

    async def click(self, element: Element) -> None:
        await self.driver.require()
        await self.wrapped.click(element)

    async def type_text(self, element: Element, text: str) -> None:
        await self.driver.require()
        await self.wrapped.type_text(element, text)

    async def select(self, element: Element, value: str) -> None:
        await self.driver.require()
        await self.wrapped.select(element, value)

    async def scroll(self, direction: str) -> None:
        await self.driver.require()
        await self.wrapped.scroll(direction)

    async def navigate(self, url: str) -> None:
        await self.driver.require()
        await self.wrapped.navigate(url)

    async def back(self) -> None:
        await self.driver.require()
        await self.wrapped.back()

    async def forward(self) -> None:
        await self.driver.require()
        await self.wrapped.forward()

    async def reload(self) -> None:
        await self.driver.require()
        await self.wrapped.reload()

    async def settle(self) -> None:
        await self.driver.require()
        await self.wrapped.settle()

    async def location(self) -> tuple[str, str]:
        await self.driver.require()
        return await self.wrapped.location()

    async def screenshot(self) -> str | None:
        await self.driver.require()
        return await self.wrapped.screenshot()

    async def read(self) -> str:
        await self.driver.require()
        return await self.wrapped.read()

    async def click_at(self, x: float, y: float) -> None:
        await self.driver.require()
        await self.wrapped.click_at(x, y)

    async def insert_text(self, text: str) -> None:
        await self.driver.require()
        await self.wrapped.insert_text(text)

    async def press(self, key: str) -> None:
        await self.driver.require()
        await self.wrapped.press(key)

    async def wheel(self, dy: float) -> None:
        await self.driver.require()
        await self.wrapped.wheel(dy)

    async def resize(self, width: int, height: int, scale: int) -> None:
        await self.driver.require()
        await self.wrapped.resize(width, height, scale)

    async def point(self, element: Element) -> tuple[float, float] | None:
        await self.driver.require()
        return await self.wrapped.point(element)

    async def capture_sign_in(self) -> SignIn | None:
        await self.driver.require()
        return await self.wrapped.capture_sign_in()


def _desktop_computer(view: runtime.EnvironmentView) -> Computer:
    if not isinstance(view, runtime.DesktopEnvironmentView):
        raise ComputerError("The desktop resource changed kind")
    return view.computer
