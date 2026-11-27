"""Authenticated views of owned live environments; disconnect only detaches."""

import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from typing import Literal
from uuid import UUID

import anyio
import httpx
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

from app.agents.browser_events import BrowserCommand, BrowserEvent
from app.agents.capabilities.browser_use._endpoint import EndpointError
from app.agents.capabilities.browser_use._page import DomainRefused
from app.agents.capabilities.computer_use._backends import ComputerError
from app.core.exceptions import (
    AppException,
    AuthorizationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.conversation_environment import ConversationEnvironment
from app.db.session import get_db_context
from app.repositories import conversation_environment as environments
from app.schemas.conversation_environment import ConversationEnvironmentRead
from app.schemas.project_context import ProjectExecutionTarget
from app.services import conversation_environment_runtime as runtime
from app.services.conversation_environment_driver import EnvironmentDriver
from app.services.conversation_environment_policy import EnvironmentSettings, current_actor
from app.services.conversation_environment_resources import EnvironmentResource
from app.services.conversation_environments import ConversationEnvironmentService
from app.services.ws_auth import authenticate_socket_key, authenticate_socket_token


class EnvironmentStateFrame(BaseModel):
    type: Literal["environment_state"] = "environment_state"
    data: ConversationEnvironmentRead


class EnvironmentBrowserFrame(BaseModel):
    type: Literal["browser_event"] = "browser_event"
    data: BrowserEvent


async def stream_environment(
    websocket: WebSocket,
    *,
    auth_token: str,
    conversation_id: UUID,
    environment_id: UUID,
    execution_target: ProjectExecutionTarget,
) -> None:
    driver: EnvironmentDriver | None = None
    view: runtime.EnvironmentView
    attached = False
    view_stack = AsyncExitStack()
    view_lock = anyio.Lock()
    send_lock = anyio.Lock()
    ciphertext: str | None = None
    sequence = 0
    checked_at = 0.0
    state: ConversationEnvironmentRead | None = None

    async def send(frame: EnvironmentStateFrame | EnvironmentBrowserFrame) -> None:
        async with send_lock:
            with anyio.fail_after(5):
                await websocket.send_text(frame.model_dump_json())

    async def resolve(
        db: AsyncSession, *, lock: bool = False, touch: bool = False
    ) -> tuple[
        AuthContext, tuple[ConversationEnvironment, EnvironmentSettings, EnvironmentResource]
    ]:
        # The handshake's CurrentUserWS can authenticate a key; manual ownership
        # must not silently promote that key to its issuer's browser session.
        if await authenticate_socket_key(db, auth_token) is not None:
            raise AuthorizationError(message="An API key cannot inherit a manual environment")
        user = await authenticate_socket_token(db, auth_token, allow_expired=True)
        row = await environments.for_socket(
            db, environment_id, user_id=user.id, conversation_id=conversation_id
        )
        if row is None or row.organization_id is None:
            raise NotFoundError(message="This environment is unavailable")
        ctx = await current_actor(db, row.organization_id, user.id)
        live = await ConversationEnvironmentService(db).live(
            ctx, conversation_id, environment_id, execution_target, lock=lock, touch=touch
        )
        return ctx, live

    async def check_driver(db: AsyncSession) -> None:
        await resolve(db, lock=True, touch=False)

    async def refresh(*, force: bool = False, touch: bool = False) -> None:
        nonlocal state, ciphertext, view, checked_at, attached
        async with get_db_context() as db:
            ctx, (row, resolved, resource) = await resolve(db, lock=touch, touch=touch)
            current = await ConversationEnvironmentService(db).read(
                ctx, conversation_id, resolved.authority.agent.id, resource.kind, execution_target
            )
            changed = row.resource_ciphertext != ciphertext
            new_ciphertext = row.resource_ciphertext
        if changed or not attached:
            async with view_lock:
                await view_stack.aclose()
                view = await view_stack.enter_async_context(runtime.open_view(resource, resolved))
                ciphertext = new_ciphertext
                attached = True
        if force or current != state:
            state = current
            await send(EnvironmentStateFrame(data=current))
        if force:
            checked_at = time.monotonic()

    async def event(
        kind: Literal[
            "browser_opened",
            "browser_frame",
            "browser_control_error",
            "browser_held",
            "browser_released",
        ],
        *,
        image: str | None = None,
        url: str | None = None,
        title: str | None = None,
        navigable: bool = False,
        detail: str | None = None,
        by_user_id: str | None = None,
    ) -> None:
        nonlocal sequence
        sequence += 1
        await send(
            EnvironmentBrowserFrame(
                data=BrowserEvent(
                    kind=kind,
                    environment_id=environment_id,
                    call_id=str(environment_id),
                    step=sequence,
                    image=image,
                    url=url,
                    title=title,
                    navigable=navigable,
                    detail=detail,
                    by_user_id=by_user_id,
                )
            )
        )

    async def frames() -> None:
        while True:
            await refresh(force=time.monotonic() - checked_at >= 30)
            async with view_lock:
                frame = await runtime.picture(view)
            await event(
                "browser_frame",
                image=frame.image,
                url=frame.url,
                title=frame.title,
                navigable=frame.navigable,
            )
            await anyio.sleep(1)

    async def resize_browser(
        ctx: AuthContext,
        row: ConversationEnvironment,
        resolved: EnvironmentSettings,
        command: BrowserCommand,
    ) -> None:
        # Fitting an idle view is layout, not a human takeover or paid activity.
        # The same physical lease still fences it against an agent or another tab.
        if row.kind != "browser":
            raise BadRequestError(message="This desktop cannot resize its physical screen")
        async with get_db_context() as db:
            current = await ConversationEnvironmentService(db).read(
                ctx, conversation_id, resolved.authority.agent.id, "browser", execution_target
            )
        if not current.can_control:
            await refresh(force=True)
            return
        if driver is not None:
            await driver.require()
            await refresh()
            async with view_lock:
                await runtime.perform(view, command)
            return
        if row.resource_key is None:
            raise NotFoundError(message="The environment has no live resource")
        candidate = EnvironmentDriver(row.resource_key, ctx, "layout", check_driver)
        try:
            try:
                await candidate.acquire()
            except ConflictError:
                # An authoritative busy state lets the viewer defer its latest fit
                # until idle; resizing must never steal control or spin on retries.
                await refresh(force=True)
                return
            await candidate.require()
            await refresh()
            async with view_lock:
                await runtime.perform(view, command)
        finally:
            await candidate.close()
        await refresh(force=True)

    async def commands() -> None:
        nonlocal driver
        while True:
            raw = await websocket.receive_text()
            if len(raw) > 16384:
                await event("browser_control_error", detail="The command is too large.")
                continue
            try:
                command = BrowserCommand.model_validate_json(raw)
            except ValidationError:
                await event("browser_control_error", detail="The command is invalid.")
                continue
            try:
                async with get_db_context() as db:
                    ctx, (row, resolved, _) = await resolve(db)
                if command.type == "take_over":
                    if driver is None:
                        if row.resource_key is None:
                            raise NotFoundError(message="The environment has no live resource")
                        candidate = EnvironmentDriver(row.resource_key, ctx, "human", check_driver)
                        try:
                            await candidate.acquire()
                        except BaseException:
                            await candidate.close()
                            raise
                        driver = candidate
                    else:
                        await driver.require()
                    await event("browser_held", by_user_id=str(ctx.subject_id))
                    await refresh(force=True, touch=True)
                elif command.type == "resize":
                    await resize_browser(ctx, row, resolved, command)
                elif command.type == "give_back":
                    if driver is not None:
                        await driver.close()
                        driver = None
                    await event("browser_released")
                    await refresh(force=True, touch=True)
                else:
                    if driver is None:
                        raise AuthorizationError(message="Take control before sending input")
                    await driver.require()
                    async with get_db_context() as db:
                        await resolve(db, lock=True, touch=True)
                    await refresh()
                    async with view_lock:
                        await runtime.perform(view, command)
            except (AppException, ComputerError, DomainRefused, EndpointError) as exc:
                detail = (
                    exc.message
                    if isinstance(exc, AppException)
                    else "The environment could not apply this command. Check the selected page and try again."
                )
                await event("browser_control_error", detail=detail)

    try:
        await refresh(force=True)
        await event("browser_opened", navigable=state is not None and state.kind == "browser")
        async with anyio.create_task_group() as tasks:

            async def guarded(action: Callable[[], Awaitable[None]]) -> None:
                try:
                    await action()
                except WebSocketDisconnect:
                    pass
                except (
                    AppException,
                    ComputerError,
                    EndpointError,
                    DomainRefused,
                    httpx.HTTPError,
                    OSError,
                ):
                    if (
                        websocket.application_state is not WebSocketState.DISCONNECTED
                        and websocket.client_state is not WebSocketState.DISCONNECTED
                    ):
                        await websocket.close(
                            code=4403,
                            reason="The original environment is unavailable or access changed",
                        )
                finally:
                    tasks.cancel_scope.cancel()

            tasks.start_soon(guarded, commands)
            tasks.start_soon(guarded, frames)
    except WebSocketDisconnect:
        pass
    except AppException, ComputerError, EndpointError, DomainRefused, httpx.HTTPError, OSError:
        if (
            websocket.application_state is not WebSocketState.DISCONNECTED
            and websocket.client_state is not WebSocketState.DISCONNECTED
        ):
            await websocket.close(
                code=4403, reason="The original environment is unavailable or access changed"
            )
    finally:

        async def detach() -> None:
            with anyio.move_on_after(15, shield=True):
                await view_stack.aclose()

        try:
            if driver is not None:
                await driver.close()
        except BaseException as release_failure:
            try:
                await detach()
            except BaseException as detach_failure:
                raise BaseExceptionGroup(
                    "Environment driver release and view detach both failed",
                    [release_failure, detach_failure],
                ) from None
            raise
        else:
            await detach()
