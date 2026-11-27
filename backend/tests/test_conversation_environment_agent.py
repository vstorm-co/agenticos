"""The real run adapter fences every input/read and closes its driver on failure."""

from contextlib import AsyncExitStack, asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.capabilities.browser_use._elements import Element
from app.agents.capabilities.browser_use._loop import PageSession
from app.agents.capabilities.computer_use._actions import TypeText
from app.agents.capabilities.computer_use._backends import Computer, ComputerError
from app.core.exceptions import AuthorizationError, ConflictError
from app.core.permissions import AuthContext
from app.services import conversation_environment_agent as adapter
from app.services.conversation_environment_driver import EnvironmentDriver

pytestmark = [pytest.mark.anyio, pytest.mark.security]


ELEMENT = Element(index=0, role="textbox", label="Draft", path="#draft")
PAGE_OPERATIONS = [
    ("snapshot", ()),
    ("click", (ELEMENT,)),
    ("type_text", (ELEMENT, "private text")),
    ("select", (ELEMENT, "choice")),
    ("scroll", ("down",)),
    ("navigate", ("https://example.com/",)),
    ("back", ()),
    ("forward", ()),
    ("reload", ()),
    ("settle", ()),
    ("location", ()),
    ("screenshot", ()),
    ("read", ()),
    ("click_at", (1.0, 2.0)),
    ("insert_text", ("private text",)),
    ("press", ("Enter",)),
    ("wheel", (120.0,)),
    ("resize", (1024, 800, 1)),
    ("point", (ELEMENT,)),
    ("capture_sign_in", ()),
]


@pytest.mark.parametrize("method,args", PAGE_OPERATIONS)
async def test_lost_physical_driver_blocks_every_page_operation_before_provider_io(method, args):
    page = AsyncMock(spec=PageSession)
    page.native_id, page.streaming = None, False
    driver = AsyncMock(spec=EnvironmentDriver)
    driver.require.side_effect = AuthorizationError(message="Access revoked")
    wrapped = adapter.DrivenPage(page, driver)
    with pytest.raises(AuthorizationError):
        await getattr(wrapped, method)(*args)
    getattr(page, method).assert_not_awaited()


async def test_page_adoption_keeps_native_identity_and_does_not_copy_or_transform_actions():
    page = AsyncMock(spec=PageSession)
    page.native_id, page.streaming = "actual-target", True
    driver = AsyncMock(spec=EnvironmentDriver)
    wrapped = adapter.DrivenPage(page, driver)
    assert wrapped.native_id == "actual-target" and wrapped.streaming
    await wrapped.type_text(ELEMENT, "unsaved input")
    page.type_text.assert_awaited_once_with(ELEMENT, "unsaved input")
    assert await wrapped.location() == page.location.return_value
    driver.require.assert_awaited()


async def test_page_stream_checks_control_before_attaching_and_detaches_only_its_view():
    page = AsyncMock(spec=PageSession)
    page.native_id, page.streaming = None, False
    delivered, closed = [], []

    @asynccontextmanager
    async def frames(send):
        try:
            await send("existing-frame")
            yield
        finally:
            closed.append(True)

    page.stream.side_effect = frames

    async def send(image):
        delivered.append(image)

    driver = AsyncMock(spec=EnvironmentDriver)
    wrapped = adapter.DrivenPage(page, driver)
    async with wrapped.stream(send):
        assert delivered == ["existing-frame"]
    assert closed == [True]
    driver.require.side_effect = ConflictError(message="Driver expired")
    with pytest.raises(ConflictError):
        async with wrapped.stream(send):
            pytest.fail("No stream after lost control")
    assert page.stream.call_count == 1


@pytest.mark.parametrize(
    "method,args", [("capture", ()), ("perform", (TypeText(text="input"),)), ("apps", ())]
)
async def test_desktop_reads_and_actions_are_refused_after_driver_loss(method, args):
    computer = AsyncMock(spec=Computer)
    computer.label = "Actual desktop"
    owner = AsyncMock(spec=adapter.AgentEnvironment)
    owner.driver = AsyncMock(spec=EnvironmentDriver)
    owner.driver.require.side_effect = AuthorizationError(message="No longer allowed")
    wrapped = adapter.DrivenComputer(computer, owner, AsyncExitStack())
    with pytest.raises(AuthorizationError):
        await getattr(wrapped, method)(*args)
    getattr(computer, method).assert_not_awaited()
    owner.driver = None
    with pytest.raises(ComputerError):
        await getattr(wrapped, method)(*args)


async def test_desktop_detach_failure_still_releases_run_driver():
    computer = AsyncMock(spec=Computer)
    computer.label = "Actual desktop"
    owner = AsyncMock(spec=adapter.AgentEnvironment)
    stack = AsyncExitStack()

    async def fail_close():
        raise OSError("Transport close failed")

    stack.push_async_callback(fail_close)
    wrapped = adapter.DrivenComputer(computer, owner, stack)
    with pytest.raises(OSError):
        await wrapped.close()
    owner.finish.assert_awaited_once()


async def test_desktop_wrapper_does_not_create_a_replacement_when_recheck_fails():
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    owner = adapter.AgentEnvironment(
        ctx,
        conversation_id=uuid4(),
        agent_id=uuid4(),
        version_id=uuid4(),
        run_id=uuid4(),
        target="agent",
        kind="desktop",
    )
    owner.acquire = AsyncMock(return_value=True)
    owner.load = AsyncMock(side_effect=AuthorizationError(message="Access revoked after claim"))
    owner.finish = AsyncMock()
    fallback = AsyncMock()
    with pytest.raises(AuthorizationError):
        await owner.wrap_computer(fallback)(AsyncMock())
    fallback.assert_not_awaited()
    owner.finish.assert_awaited_once()


async def test_a_closed_run_adapter_cannot_be_reused_by_a_later_run():
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    owner = adapter.AgentEnvironment(
        ctx,
        conversation_id=uuid4(),
        agent_id=uuid4(),
        version_id=uuid4(),
        run_id=uuid4(),
        target="agent",
        kind="browser",
    )
    await owner.finish()
    with pytest.raises(ConflictError):
        await owner.acquire()
