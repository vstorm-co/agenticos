"""Every surface keeps the run principal and uses the same operation service."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.audience import RunAudience
from app.agents.capabilities import _integration_toolset as tools
from app.agents.deps import AgentDeps
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext
from app.services.integrations import AccountSelection, IntegrationService
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed
from app.workflows.nodes.integration_action import _handler as nodes

pytestmark = pytest.mark.anyio


@pytest.fixture
def native_calls(monkeypatch):
    @asynccontextmanager
    async def session():
        yield AsyncMock()

    monkeypatch.setattr(tools, "get_db_context", session)
    monkeypatch.setattr(nodes, "get_worker_db_context", session)
    call = AsyncMock(return_value={"id": "remote-result"})
    monkeypatch.setattr(IntegrationService, "run", call)
    return call


def dispatch(*, public=False):
    org = uuid4()
    return context.DispatchContext(
        organization_id=org,
        workflow_run_id=uuid4(),
        node_run_id=uuid4(),
        node_instance_id=uuid4(),
        attempt_no=1,
        auth=AuthContext(organization_id=org, user_id=uuid4(), role="owner"),
        resumed_agent_run_id=None,
        public_origin=public,
    )


async def test_workflow_node_calls_the_same_operation_as_the_agent_tool(native_calls):
    current = dispatch()
    with context.dispatching_as(current):
        result = await nodes.handler_for("gmail", "search_threads")(
            AccountSelection(), nodes.IntegrationInput(query={"q": "in:inbox"})
        )
    assert isinstance(result, Completed) and result.output.result == {"id": "remote-result"}
    assert native_calls.await_args.kwargs["person_id"] == current.auth.user_id
    assert native_calls.await_args.kwargs["organization_id"] == current.organization_id
    assert native_calls.await_args.kwargs["workflow_run_id"] == current.workflow_run_id
    assert native_calls.await_args.kwargs["query"] == {"q": "in:inbox"}


@pytest.mark.parametrize("configured", [False, True])
async def test_public_or_unconfigured_workflows_cannot_borrow_personal_accounts(
    native_calls, configured
):
    with context.dispatching_as(dispatch(public=True)):
        result = await nodes.handler_for("gmail", "search_threads")(
            AccountSelection() if configured else None, nodes.IntegrationInput()
        )
    assert isinstance(result, Failed)
    native_calls.assert_not_awaited()


async def test_workflow_provider_refusal_is_a_nonbypassable_node_failure(native_calls):
    native_calls.side_effect = AuthorizationError(message="reconnect account")
    with context.dispatching_as(dispatch()):
        result = await nodes.handler_for("gmail", "search_threads")(
            AccountSelection(), nodes.IntegrationInput()
        )
    assert (
        isinstance(result, Failed)
        and result.error.message == "reconnect account"
        and not result.error.bypassable
    )


async def test_publish_checks_the_account_without_spending_its_credential(monkeypatch):
    check = nodes.check_for("gmail")
    ctx = dispatch().auth
    account = AsyncMock(return_value=object())
    monkeypatch.setattr(IntegrationService, "account", account)
    assert await check(AsyncMock(), ctx, AccountSelection()) == []
    assert account.await_args.kwargs["person_id"] == ctx.user_id
    account.side_effect = AuthorizationError(message="not yours")
    assert await check(AsyncMock(), ctx, AccountSelection()) == [("account", "not yours")]
    assert await check(AsyncMock(), ctx, nodes.IntegrationInput()) == [
        ("account", "Choose an integration account")
    ]


@pytest.mark.parametrize(
    "audience", [None, RunAudience(user_id=uuid4(), room_key="room:slack:shared")]
)
async def test_agent_tools_do_not_read_personal_data_to_a_room(native_calls, audience):
    deps = AgentDeps(organization_id=uuid4(), run_person=uuid4(), audience=audience)
    ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage(), prompt="test")
    tool = tools.build_toolset("gmail", AccountSelection()).tools["gmail_search_threads"].function
    assert "error" in await tool(ctx)
    native_calls.assert_not_awaited()


async def test_agent_tool_uses_the_current_run_person_and_reports_account_refusals(native_calls):
    person = uuid4()
    deps = AgentDeps(
        organization_id=uuid4(),
        run_id=uuid4(),
        run_person=person,
        audience=RunAudience(user_id=person),
    )
    ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage(), prompt="test")
    tool = tools.build_toolset("gmail", AccountSelection()).tools["gmail_search_threads"].function
    assert await tool(ctx, query={"q": "unread"}) == {"id": "remote-result"}
    assert native_calls.await_args.kwargs["person_id"] == person
    assert native_calls.await_args.kwargs["agent_run_id"] == deps.run_id
    native_calls.side_effect = AuthorizationError(message="reconnect")
    assert await tool(ctx) == {"error": "reconnect"}
    deps.organization_id = None
    assert "error" in await tool(ctx)


async def test_a_disabled_product_tool_is_absent_from_the_runtime():
    toolset = tools.build_toolset(
        "gmail", AccountSelection(disabled_tools=["gmail_search_threads"])
    )
    assert "gmail_search_threads" not in toolset.tools
