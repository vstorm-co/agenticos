"""A Python action has the same version, resource grants and export boundary as a canvas step."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.permissions import AuthContext
from app.db.models.workflow_run import NodeRun
from app.repositories import virtual_table_repo
from app.services import agent_registry
from app.services.workflow_execution.script_calls import configured_step
from app.services.workflow_registry import WorkflowRegistryService, _table_references
from app.workflows.contracts.io import Binding, LiteralValue, TableIORef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.portable import portable
from app.workflows.graph.validate import graph_size_problems, validate_graph
from app.workflows.python_actions import PYTHON_ACTIONS, ActionBinding, PythonActionsConfig

pytestmark = pytest.mark.anyio


def _script(actions: object) -> WorkflowGraph:
    step = NodeInstance(
        id=uuid4(),
        definition_id=PYTHON_ACTIONS,
        definition_version=1,
        config={"code": "args", "actions": actions},
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=step.id, nodes=(step,))


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")


async def test_catalog_offers_callable_actions_and_decisions_but_not_graph_wiring(
    mock_db_session: AsyncSession,
):
    catalog = await WorkflowRegistryService(mock_db_session).node_catalog()
    offered = {entry.id for entry in catalog.items if entry.python_callable}
    assert "flow.await_reply" in offered
    assert {
        "mcp.call",
        "agent.run",
        "workflow.run",
        "flow.wait",
        "knowledge.search",
        "table.record.upsert",
        "human.approval",
        "ai.classify",
        "table.record.exists",
    } <= offered
    assert (
        not {
            PYTHON_ACTIONS,
            "core.input",
            "trigger.manual",
            "core.output",
            "webhook.respond",
            "control.foreach",
            "logic.switch",
            "error.handle",
        }
        & offered
    )


@pytest.mark.parametrize("alias", ["args", "_private", "is", "len", "a.b", "3times", "é"])
def test_action_names_must_be_callable_python_identifiers(alias: str):
    with pytest.raises(ValidationError, match="function name"):
        PythonActionsConfig.model_validate(
            {"code": "args", "actions": {alias: {"type": "debug.echo"}}}
        )


@pytest.mark.parametrize(
    ("binding", "problem"),
    [
        ({"type": "debug.echo", "version": 500}, "Unknown version"),
        ({"type": "trigger.manual"}, "not callable"),
        ({"type": PYTHON_ACTIONS}, "not callable"),
        ({"type": "table.record.get", "config": {}}, "table"),
        ({"type": "flow.resume_link", "config": {"extra": True}}, "no configuration"),
    ],
)
def test_invalid_or_graph_only_bindings_are_refused(binding: dict, problem: str):
    with pytest.raises(ValidationError, match=problem):
        ActionBinding.model_validate(binding)


def test_a_timer_and_a_configless_action_can_be_bound():
    wait = ActionBinding(type="flow.wait", config={"seconds": 2}).binding_config()
    assert wait is not None and wait.model_dump()["seconds"] == 2
    assert ActionBinding(type="flow.resume_link").binding_config() is None


@pytest.mark.security
async def test_publish_checks_each_bound_table_as_the_author(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncSession
):
    table = TableIORef(table_id=uuid4(), schema_version=1)
    graph = _script(
        {"case": {"type": "table.record.get", "config": {"table": table.model_dump(mode="json")}}}
    )
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(virtual_table_repo, "get_table", lookup)
    ctx = _ctx()
    with pytest.raises(GraphValidationError) as refused:
        await validate_graph(mock_db_session, ctx, graph)
    assert {
        "field": f"nodes.{graph.entry_node_id}.config.actions.case.config.table",
        "message": "This table does not exist or is not accessible",
    } in refused.value.details["fields"]
    lookup.assert_awaited_once_with(
        mock_db_session, table.table_id, organization_id=ctx.organization_id
    )


@pytest.mark.security
async def test_binding_does_not_grant_a_missing_deployment_scope(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncSession
):
    monkeypatch.setattr(agent_registry, "DEFAULT_GRANTED_SCOPES", frozenset())
    graph = _script({"subscript": {"type": "code.python.simple", "config": {"code": "print(1)"}}})
    with pytest.raises(GraphValidationError) as refused:
        await validate_graph(mock_db_session, _ctx(), graph)
    assert {
        "field": f"nodes.{graph.entry_node_id}.config.actions.subscript",
        "message": "This deployment has not granted: code:execute",
    } in refused.value.details["fields"]


@pytest.mark.security
@pytest.mark.parametrize("field", ["code", "actions", "actions.lookup"])
async def test_runtime_data_cannot_replace_the_reviewed_program_or_bindings(
    field: str, mock_db_session: AsyncSession
):
    graph = _script({})
    binding = Binding(
        target_node_id=graph.entry_node_id,
        target_field=field,
        source=LiteralValue(value="print(1)"),
    )
    with pytest.raises(GraphValidationError) as refused:
        await validate_graph(
            mock_db_session, _ctx(), graph.model_copy(update={"bindings": (binding,)})
        )
    assert any(
        "fixed in the workflow version" in error["message"]
        for error in refused.value.details["fields"]
    )


def test_bound_actions_count_toward_the_publish_work_limit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "WORKFLOW_GRAPH_MAX_NODES", 1)
    assert graph_size_problems(_script({"echo": {"type": "debug.echo"}}))


def test_export_removes_nested_resource_pins_and_table_dependencies_still_count():
    table = TableIORef(table_id=uuid4(), schema_version=1, column_ids=(uuid4(),))
    mailbox = str(uuid4())
    graph = _script(
        {
            "lookup": {
                "type": "table.record.get",
                "config": {"table": table.model_dump(mode="json")},
            },
            "reply": {
                "type": "flow.await_reply",
                "config": {"provider": "google", "connection_id": mailbox},
            },
        }
    )
    assert _table_references(graph.model_dump(mode="json")) == [(table.table_id, table.column_ids)]
    carried, missing = portable(graph)
    assert str(table.table_id) not in carried.model_dump_json()
    assert mailbox not in carried.model_dump_json()
    assert [(m.field, m.kind) for m in missing] == [
        ("actions.lookup.config.table", "table"),
        ("actions.reply.config.connection_id", "mcp_connection"),
    ]
    assert carried.nodes[0].config["actions"]["lookup"]["type"] == "table.record.get"


@pytest.mark.parametrize(
    "actions",
    [
        123,
        {"f": []},
        {"f": {"type": "debug.echo", "version": False}},
        {"f": {"type": "unknown"}},
        {"f": {"type": PYTHON_ACTIONS}},
    ],
)
def test_export_does_not_guess_how_to_strip_an_unrecognized_action(actions: object):
    with pytest.raises(GraphValidationError):
        portable(_script(actions))


def test_a_stale_or_mismatched_wait_cannot_receive_a_callback():
    graph = _script(
        {
            "external": {"type": "flow.wait", "config": {"until_called": True}},
            "timer": {"type": "flow.wait", "config": {"seconds": 5}},
        }
    )
    child = NodeRun(
        node_instance_id=graph.entry_node_id, scope_path=[{"action": "missing", "index": 0}]
    )
    assert configured_step(graph.node_by_id, child) is None
    assert configured_step({}, child) is None
    child.scope_path = [{"action": "timer", "index": 0}]
    assert configured_step(graph.node_by_id, child) == ("flow.wait", {"seconds": 5})


def test_each_page_may_override_the_offset_but_not_the_bound_table_or_limit():
    table = TableIORef(table_id=uuid4(), schema_version=1)
    query = ActionBinding(
        type="table.record.query", config={"table": table.model_dump(mode="json"), "limit": 10}
    )
    first, _ = query.resolve_call({})
    next_page, data = query.resolve_call({"skip": 10})
    assert next_page is not None and first is not None and data is None
    assert first.model_dump()["skip"] == 0
    assert next_page.model_dump() == {**first.model_dump(), "skip": 10}
    with pytest.raises(ValidationError):
        query.resolve_call({"skip": -1})
    for name in ("table", "limit", "unknown"):
        with pytest.raises(ValueError, match="no callable data field"):
            query.resolve_call({name: 1})


def test_http_url_and_body_are_validated_by_their_own_schemas():
    request = ActionBinding(
        type="http.request", config={"method": "POST", "url": "https://example.org"}
    )
    config, data = request.resolve_call({"url": "https://example.org/api", "body": {"count": 2}})
    assert config is not None and config.model_dump()["url"] == "https://example.org/api"
    assert data is not None and data.model_dump() == {"body": {"count": 2}}
    for field in ("auth", "headers", "method", "idempotency_key_header", "timeout_seconds"):
        with pytest.raises(ValueError, match="no callable data field"):
            request.resolve_call({field: "ignored"})


def test_script_inputs_win_over_config_defaults_and_required_fields_are_still_required():
    echo = ActionBinding(type="debug.echo", config={"message": "default"})
    config, data = echo.resolve_call({"message": "override"})
    assert config is not None and config.model_dump()["message"] == "default"
    assert data is not None and data.model_dump()["message"] == "override"
    assert echo.resolve_call({})[1] is None
    file = ActionBinding(type="convert.text_to_file")
    with pytest.raises(ValidationError):
        file.resolve_call({"filename": "ticket.txt"})
    config, data = file.resolve_call({"filename": "ticket.txt", "text": "case"})
    assert config is not None and config.model_dump()["filename"] == "ticket.txt"
    assert data is not None and data.model_dump()["text"] == "case"


@pytest.mark.parametrize("action_type", ["http.request", "http.upload", "http.download"])
def test_a_script_can_supply_the_required_http_url_at_call_time(action_type: str):
    binding = ActionBinding(type=action_type)
    call_inputs = (
        {
            "file": {
                "kind": "file",
                "file_id": str(uuid4()),
                "content_type": "text/plain",
                "byte_size": 10,
            }
        }
        if action_type == "http.upload"
        else {}
    )
    with pytest.raises(ValidationError, match="url"):
        binding.resolve_call(call_inputs)
    config, _ = binding.resolve_call({**call_inputs, "url": "https://example.org/report"})
    assert config is not None and config.model_dump()["url"] == "https://example.org/report"
    for bad in ("", None):
        with pytest.raises(ValidationError, match="url"):
            ActionBinding(type=action_type, config={"url": bad})
    with pytest.raises(ValidationError, match="timeout_seconds"):
        ActionBinding(type=action_type, config={"timeout_seconds": -1})


@pytest.mark.security
async def test_an_omitted_http_url_does_not_hide_a_vault_reference_from_publish(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncSession
):
    from app.repositories import organization_secret as secret_repo

    secret_id = uuid4()
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(secret_repo, "get", lookup)
    graph = _script(
        {
            "fetch": {
                "type": "http.request",
                "config": {"auth": {"kind": "bearer", "secret_id": str(secret_id)}},
            }
        }
    )
    ctx = _ctx()
    with pytest.raises(GraphValidationError) as refused:
        await validate_graph(mock_db_session, ctx, graph)
    assert any(
        error["field"].endswith("actions.fetch.config.auth.secret_id")
        for error in refused.value.details["fields"]
    )
    lookup.assert_awaited_once_with(mock_db_session, secret_id, organization_id=ctx.organization_id)


@pytest.mark.security
async def test_a_computed_table_name_does_not_hide_create_permission_or_fixed_columns(
    mock_db_session: AsyncSession,
):
    columns = [{"label": "Title", "type": "text"}]
    graph = _script({"create": {"type": "table.create", "config": {"columns": columns}}})
    viewer = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="viewer")
    with pytest.raises(GraphValidationError) as refused:
        await validate_graph(mock_db_session, viewer, graph)
    assert any(
        error["message"] == "You cannot create tables" for error in refused.value.details["fields"]
    )
    with pytest.raises(ValidationError, match="columns"):
        ActionBinding(type="table.create")
    with pytest.raises(ValidationError, match="Only a GET fetches pages"):
        ActionBinding(
            type="http.request",
            config={
                "method": "POST",
                "pagination": {"mode": "page", "items_path": "items", "param": "page"},
            },
        )
