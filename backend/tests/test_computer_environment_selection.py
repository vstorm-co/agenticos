"""Owned adapters must not intercept the user's explicitly paired local screen."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.capabilities.computer_use import ComputerUse
from app.agents.capabilities.computer_use._backends import ComputerFactory, ComputerFactoryDecorator
from tests.test_computer_use import _ctx, _Desktop
from tests.workspaces import document_workspace

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("local", [False, True])
async def test_decorated_factory_selects_local_screen_before_remote_environment(local):
    original_screen = _Desktop()
    owned_screen = _Desktop()
    original = AsyncMock(return_value=original_screen)
    remote = AsyncMock(return_value=owned_screen)
    wrapped = []

    def decorate(factory: ComputerFactory) -> ComputerFactory:
        wrapped.append(factory)
        return remote

    capability = ComputerUse(
        factory=original,
        factory_decorator=ComputerFactoryDecorator(decorate),
        local_session_id=uuid4() if local else None,
    )
    tools = capability.get_toolset()
    assert capability.get_toolset() is tools
    assert wrapped == [original]
    ctx = _ctx()
    ctx.workspace = document_workspace()
    async with tools:
        desktop = await tools.session.desktop(ctx)
        assert desktop is (original_screen if local else owned_screen)
    (original if local else remote).assert_awaited_once_with(ctx.workspace)
    (remote if local else original).assert_not_awaited()
