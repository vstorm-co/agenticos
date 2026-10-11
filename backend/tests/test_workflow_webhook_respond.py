"""The Respond to webhook step: what it records, and the headers it refuses."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from app.workflows.nodes.webhook_respond import WebhookRespondConfig, WebhookRespondInput
from app.workflows.nodes.webhook_respond._handler import handle
from app.workflows.triggers import WEBHOOK, WEBHOOK_RESPOND, answers_webhook

pytestmark = pytest.mark.anyio


def _dispatching() -> context.DispatchContext:
    return context.DispatchContext(
        organization_id=uuid.uuid4(),
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=MagicMock(),
        resumed_agent_run_id=None,
    )


def _node(definition_id: str) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        layout=NodePosition(x=0, y=0),
    )


async def test_it_records_the_answer_and_hands_it_on():
    config = WebhookRespondConfig(status_code=201, headers={"X-Lead": "yes"})
    with context.dispatching_as(_dispatching()) as scope:
        result = await handle(config, WebhookRespondInput(body={"id": 7}))

    answer = {"status_code": 201, "headers": {"X-Lead": "yes"}, "body": {"id": 7}}
    assert isinstance(result, Completed)
    assert result.output.model_dump(mode="json") == answer
    assert scope.webhook_response == answer


async def test_nothing_configured_or_bound_answers_200_with_null():
    with context.dispatching_as(_dispatching()) as scope:
        await handle(None, None)
    assert scope.webhook_response == {"status_code": 200, "headers": {}, "body": None}


@pytest.mark.security
@pytest.mark.parametrize(
    "headers",
    [
        {"Set-Cookie": "session=x"},
        {"Content-Type": "text/html"},
        {"Access-Control-Allow-Origin": "*"},
        {"Cross-Origin-Opener-Policy": "unsafe-none"},
        {"Bad Header": "x"},
        {"X-Split": "a\r\nSet-Cookie: session=x"},
        {"X-Long": "x" * 1025},
    ],
    ids=["cookie", "content-type", "cors", "cross-origin", "not-a-name", "crlf", "too-long"],
)
def test_a_header_the_api_owns_or_one_that_is_not_a_header_is_refused(headers):
    with pytest.raises(ValidationError):
        WebhookRespondConfig(headers=headers)


@pytest.mark.parametrize("status_code", [199, 600])
def test_a_status_outside_200_to_599_is_refused(status_code):
    with pytest.raises(ValidationError):
        WebhookRespondConfig(status_code=status_code)


def test_a_graph_answers_its_webhook_only_when_it_holds_the_step():
    trigger, respond = _node(WEBHOOK), _node(WEBHOOK_RESPOND)
    assert answers_webhook(WorkflowGraph(entry_node_id=trigger.id, nodes=(trigger, respond)))
    assert not answers_webhook(WorkflowGraph(entry_node_id=trigger.id, nodes=(trigger,)))


def test_an_answer_named_outside_a_dispatch_goes_nowhere():
    context.report_webhook_response({"status_code": 200, "headers": {}, "body": None})
