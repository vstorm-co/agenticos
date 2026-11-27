"""Only an ordinary private web-chat run receives the lazy owned GUI adapters."""

from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.capabilities.browser_use._toolset import RetainedBrowser
from app.db.models.agent_run import RunSurface
from tests.test_agent_runner import (
    _ctx,
)
from tests.test_agent_runner import (
    _in_no_group as _in_no_group,
)
from tests.test_agent_runner import (
    _no_connected_chat_bindings as _no_connected_chat_bindings,
)
from tests.test_agent_runner import (
    _no_current_cap as _no_current_cap,
)
from tests.test_agent_runner import (
    _nobody_the_account_describes as _nobody_the_account_describes,
)
from tests.test_agent_runner_voice import runner_with_mocks as runner_with_mocks

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def case(runner_with_mocks, monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_runner.conversation_share_repo.has_edit_share",
        AsyncMock(return_value=False),
    )
    return runner_with_mocks


@pytest.mark.parametrize("surface", [RunSurface.WEB, RunSurface.API, RunSurface.SLACK])
@pytest.mark.parametrize("keyed", [False, True])
async def test_runner_only_wires_private_person_owned_web_environments(case, surface, keyed):
    ctx = _ctx()
    if keyed:
        ctx = replace(ctx, api_key_id=uuid4())
    await case.service.prepare(ctx, uuid4(), surface=surface, conversation_id=uuid4())
    resources = case.build_agent.call_args.kwargs["resources"]
    expected = surface is RunSurface.WEB and not keyed
    assert ("conversation_browser" in resources) is expected
    assert ("conversation_desktop" in resources) is expected
    if expected:
        assert isinstance(resources["conversation_browser"], RetainedBrowser)
    case.opened.assert_awaited_once()


@pytest.mark.parametrize("option", ["test", "public_origin", "organization_mcp_only"])
async def test_auxiliary_and_public_web_runs_keep_their_existing_lifecycle(case, option):
    await case.service.prepare(
        _ctx(), uuid4(), surface=RunSurface.WEB, conversation_id=uuid4(), **{option: True}
    )
    resources = case.build_agent.call_args.kwargs["resources"]
    assert "conversation_browser" not in resources
    assert "conversation_desktop" not in resources
