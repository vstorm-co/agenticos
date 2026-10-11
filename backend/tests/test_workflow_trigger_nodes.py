"""The trigger nodes a workflow starts from, and the rule that it has one (unit by unit).

`tests/integration/test_workflow_exposures.py` and `test_table_triggers.py`
publish and fire them against a real database; what is left here is each
handler handing on the run's input, the one refusal only a test run can reach,
and the graph rule placing a trigger at the entry.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.core.permissions import AuthContext
from app.services.workflow_execution import context
from app.workflows import _registry
from app.workflows.contracts.results import Completed, Failed
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import _rule_1_single_entry
from app.workflows.nodes._channels import check_listening_bot
from app.workflows.nodes._triggers import TableRecordTriggerConfig
from app.workflows.nodes.trigger_channel_message._handler import ChannelMessageTriggerConfig
from app.workflows.nodes.trigger_channel_message._handler import handle as channel_message
from app.workflows.nodes.trigger_chat._handler import handle as chat
from app.workflows.nodes.trigger_schedule._handler import handle as schedule
from app.workflows.nodes.trigger_table_record._handler import check_resources
from app.workflows.nodes.trigger_table_record._handler import handle as table_record
from app.workflows.nodes.trigger_webhook._handler import handle as webhook
from app.workflows.triggers import CHAT, MANUAL, SCHEDULE, TABLE_RECORD, WEBHOOK, live_trigger

pytestmark = pytest.mark.anyio


def _dispatch(run_input: dict[str, Any]) -> context.DispatchContext:
    return context.DispatchContext(
        organization_id=uuid.uuid4(),
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner"),
        resumed_agent_run_id=None,
        run_input=run_input,
    )


_TABLE, _RECORD, _MEMBER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
_FIRED = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)

HANDED_ON = [
    (
        chat,
        {"prompt": "Hi", "conversation_id": str(_RECORD), "user_id": str(_MEMBER)},
        {"prompt": "Hi", "conversation_id": _RECORD, "user_id": _MEMBER},
    ),
    (
        channel_message,
        {
            "platform": "slack",
            "bot_id": str(_TABLE),
            "channel_id": "C1",
            "chat_type": "group",
            "text": "refund",
            "sender": {"platform_user_id": "U1"},
        },
        {
            "platform": "slack",
            "bot_id": _TABLE,
            "channel_id": "C1",
            "thread_id": "",
            "chat_type": "group",
            "message_id": None,
            "text": "refund",
            "sender": {
                "platform_user_id": "U1",
                "username": None,
                "display_name": None,
                "user_id": None,
            },
        },
    ),
    (
        webhook,
        {"body": {"lead": 1}, "delivery_id": "d-1"},
        {"body": {"lead": 1}, "delivery_id": "d-1"},
    ),
    (
        schedule,
        {"fired_at": _FIRED.isoformat(), "input": {"region": "eu"}},
        {"fired_at": _FIRED, "input": {"region": "eu"}},
    ),
    (
        table_record,
        {
            "table_id": str(_TABLE),
            "record_id": str(_RECORD),
            "values": {"c1": "ada@example.com"},
            "fields": {"Email": "ada@example.com"},
            "author_id": None,
        },
        # A run started before triggers knew of changes reads as an addition.
        {
            "table_id": _TABLE,
            "record_id": _RECORD,
            "event": "created",
            "values": {"c1": "ada@example.com"},
            "fields": {"Email": "ada@example.com"},
            "before": None,
            "changed": [],
            "author_id": None,
        },
    ),
]


@pytest.mark.parametrize(
    ("handle", "run_input", "output"),
    HANDED_ON,
    ids=["chat", "channel", "webhook", "schedule", "table"],
)
async def test_a_trigger_hands_the_graph_what_its_surface_started_the_run_with(
    handle, run_input: dict[str, Any], output: dict[str, Any]
):
    with context.dispatching_as(_dispatch(run_input)):
        result = await handle(None, None)
    assert isinstance(result, Completed)
    assert result.output.model_dump() == output


@pytest.mark.parametrize("handle", [chat, channel_message, webhook, schedule, table_record])
async def test_a_test_run_started_with_the_wrong_shape_fails_the_trigger(handle):
    with context.dispatching_as(_dispatch({"anything": "else"})):
        result = await handle(None, None)
    assert isinstance(result, Failed)
    assert result.error.code == "TRIGGER_INPUT_INVALID"


def test_a_channel_trigger_takes_the_chats_and_words_it_names():
    config = ChannelMessageTriggerConfig(
        bot_id=_TABLE, chat_types=("group",), text_contains="Refund"
    )
    assert config.takes(chat_type="group", text="a REFUND please")
    assert not config.takes(chat_type="group", text="hello")
    assert not config.takes(chat_type="private", text="refund")
    assert ChannelMessageTriggerConfig(bot_id=_TABLE).takes(chat_type="private", text="hi")
    with pytest.raises(ValidationError, match="named once"):
        ChannelMessageTriggerConfig(bot_id=_TABLE, chat_types=("group", "group"))


async def test_a_channel_trigger_checks_nothing_it_was_not_configured_with():
    assert await check_listening_bot(MagicMock(), MagicMock(), MagicMock()) == []


async def test_a_table_trigger_checks_nothing_it_was_not_configured_with():
    assert await check_resources(MagicMock(), MagicMock(), MagicMock()) == []


async def test_a_table_trigger_with_no_filters_checks_only_its_table(monkeypatch):
    checked = AsyncMock(return_value=[])
    monkeypatch.setattr("app.workflows.nodes.trigger_table_record._handler.check_table", checked)
    config = TableRecordTriggerConfig.model_validate(
        {"table": {"table_id": str(_TABLE), "schema_version": 1}}
    )
    assert await check_resources(MagicMock(), MagicMock(), config) == []
    checked.assert_awaited_once()


async def test_a_table_trigger_watches_only_columns_a_record_stores(monkeypatch):
    stored, worked_out, archived = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(
        "app.workflows.nodes.trigger_table_record._handler.check_table",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.workflows.nodes.trigger_table_record._handler.virtual_table_repo.get_schema_version",
        AsyncMock(
            return_value=SimpleNamespace(
                columns=[
                    {"id": str(stored), "label": "Score", "type": "integer"},
                    {"id": str(worked_out), "label": "Total", "type": "formula", "formula": "1"},
                    {"id": str(archived), "label": "Old", "type": "text", "archived": True},
                ]
            )
        ),
    )
    config = TableRecordTriggerConfig.model_validate(
        {
            "table": {
                "table_id": str(_TABLE),
                "schema_version": 1,
                "column_ids": [str(stored), str(worked_out), str(archived)],
            },
            "events": ["updated"],
        }
    )

    problems = await check_resources(MagicMock(), MagicMock(), config)

    assert [field for field, _ in problems] == ["table.column_ids.1", "table.column_ids.2"]


def test_a_table_trigger_starts_on_added_records_unless_told_more_and_names_each_once():
    table = {"table_id": str(_TABLE), "schema_version": 1}

    assert TableRecordTriggerConfig.model_validate({"table": table}).events == ("created",)
    assert TableRecordTriggerConfig.model_validate(
        {"table": table, "events": ["updated", "deleted"]}
    ).events == ("updated", "deleted")
    for events in ([], ["created", "created"], ["renamed"]):
        with pytest.raises(ValidationError):
            TableRecordTriggerConfig.model_validate({"table": table, "events": events})


def test_every_trigger_is_in_the_catalog_under_one_category():
    by_id = {definition.id: definition for definition in _registry.all_node_definitions()}
    triggers = {MANUAL, CHAT, WEBHOOK, SCHEDULE, TABLE_RECORD}
    assert {by_id[trigger].category for trigger in triggers} == {"triggers"}
    # None takes an input: a trigger is where a graph begins.
    assert all(by_id[trigger].input_schema is None for trigger in triggers)


def _node(definition_id: str, x: int = 0) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config={"message": "hi"} if definition_id == "debug.echo" else {},
        layout=NodePosition(x=x, y=0),
    )


def _edge(source: NodeInstance, target: NodeInstance) -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port="out",
        target_node_id=target.id,
        target_port="in",
    )


class TestOneTriggerAtTheEntry:
    def test_a_trigger_at_the_entry_is_the_one_way_in(self):
        entry, step = _node(WEBHOOK), _node("debug.echo", 300)
        graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry, step))
        assert _rule_1_single_entry(graph) == []
        assert live_trigger(graph) == WEBHOOK

    def test_a_graph_starting_from_a_step_starts_by_hand(self):
        entry = _node("debug.echo")
        graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))
        assert _rule_1_single_entry(graph) == []
        assert live_trigger(graph) is None

    def test_a_second_trigger_is_refused_on_that_node(self):
        entry, other = _node(MANUAL), _node(SCHEDULE, 300)
        graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry, other))
        assert _rule_1_single_entry(graph) == [
            (f"nodes.{other.id}", "A workflow starts from one trigger, and this is not it")
        ]

    def test_a_trigger_that_is_not_where_the_graph_starts_is_refused(self):
        entry, trigger = _node("debug.echo"), _node(CHAT, 300)
        graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry, trigger))
        assert [field for field, _ in _rule_1_single_entry(graph)] == [f"nodes.{trigger.id}"]

    def test_a_node_whose_definition_is_gone_is_not_counted_as_a_trigger(self):
        entry, gone = _node(MANUAL), _node("gone.node", 300)
        graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry, gone), edges=())
        assert _rule_1_single_entry(graph) == []

    def test_the_entry_rules_before_it_still_apply(self):
        entry, step = _node(MANUAL), _node("debug.echo", 300)
        looped = WorkflowGraph(
            entry_node_id=entry.id, nodes=(entry, step), edges=(_edge(step, entry),)
        )
        assert [field for field, _ in _rule_1_single_entry(looped)] == ["entry_node_id"]
