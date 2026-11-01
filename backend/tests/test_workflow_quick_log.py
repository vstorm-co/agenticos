"""A step's Quick Log: its setting on the graph, its validation, and how its message renders."""

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.db.models.workflow_log_entry import WorkflowLogEntry
from app.db.models.workflow_run import WorkflowRunMode
from app.services.workflow_execution import dispatcher
from app.services.workflow_execution import quick_log as writer
from app.workflows.contracts.policy import NodePolicy
from app.workflows.contracts.results import WorkflowError
from app.workflows.graph.model import (
    DEFAULT_QUICK_LOG_MESSAGE,
    NodeInstance,
    NodePosition,
    QuickLog,
    WorkflowGraph,
)
from app.workflows.graph.portable import portable
from app.workflows.graph.quick_log import references, refused_reference, render
from app.workflows.graph.validate import (
    _quick_log_problems,
    _resolve_definitions,
    instance_ports,
)

pytestmark = pytest.mark.anyio


def _step(
    definition_id: str = "logic.if",
    *,
    quick_log: QuickLog | None = None,
    policy: NodePolicy | None = None,
    config: dict[str, Any] | None = None,
) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
        quick_log=quick_log,
        policy=policy,
    )


def _problems(step: NodeInstance) -> list[tuple[str, str]]:
    graph = WorkflowGraph(entry_node_id=step.id, nodes=(step,))
    return _quick_log_problems(graph, instance_ports(graph, _resolve_definitions(graph)))


class TestTheSetting:
    def test_a_step_has_no_quick_log_until_it_is_given_one(self):
        assert _step().quick_log is None

    def test_the_message_defaults_and_every_output_logs(self):
        quick_log = QuickLog()
        assert quick_log.message == DEFAULT_QUICK_LOG_MESSAGE == "{{step}} → {{outcome}}"
        assert quick_log.outputs is None

    @pytest.mark.parametrize("message", ["", "x" * 501])
    def test_a_message_is_one_to_five_hundred_characters(self, message: str):
        with pytest.raises(ValidationError):
            QuickLog(message=message)

    def test_a_message_postgres_cannot_store_is_refused(self):
        with pytest.raises(ValidationError):
            QuickLog(message="a\x00b")

    def test_it_takes_no_other_field(self):
        with pytest.raises(ValidationError):
            QuickLog.model_validate({"message": "x", "table": "t"})

    def test_a_stored_graph_without_it_loads_unchanged(self):
        step = _step()
        stored = step.model_dump(mode="json")
        stored.pop("quick_log")
        assert NodeInstance.model_validate(stored).quick_log is None

    def test_it_survives_a_dump_and_load_and_an_export(self):
        step = _step(quick_log=QuickLog(message="Sent {{to}}", outputs=("true",)))
        again = NodeInstance.model_validate(step.model_dump(mode="json"))
        assert again.quick_log == step.quick_log
        carried, _unresolved = portable(WorkflowGraph(entry_node_id=step.id, nodes=(step,)))
        assert carried.nodes[0].quick_log == step.quick_log


class TestValidation:
    def test_a_step_with_no_quick_log_has_no_problem(self):
        assert _problems(_step()) == []

    def test_the_default_message_and_every_output_are_fine(self):
        assert _problems(_step(quick_log=QuickLog())) == []

    def test_outputs_may_name_the_ports_the_step_has(self):
        step = _step(quick_log=QuickLog(outputs=("true", "false")))
        assert _problems(step) == []

    def test_an_output_the_step_does_not_have_is_a_problem_at_its_index(self):
        step = _step(quick_log=QuickLog(outputs=("true", "maybe")))
        assert _problems(step) == [
            (f"nodes.{step.id}.quick_log.outputs.1", "This step has no output 'maybe'")
        ]

    def test_an_input_port_is_not_an_output(self):
        step = _step(quick_log=QuickLog(outputs=("in",)))
        assert _problems(step)[0][0] == f"nodes.{step.id}.quick_log.outputs.0"

    def test_error_is_an_output_only_of_a_step_that_routes_its_errors(self):
        plain = _step(quick_log=QuickLog(outputs=("error",)))
        assert _problems(plain)[0][0] == f"nodes.{plain.id}.quick_log.outputs.0"
        routing = _step(quick_log=QuickLog(outputs=("error",)), policy=NodePolicy(on_error="route"))
        assert _problems(routing) == []

    def test_a_port_the_steps_config_declares_is_an_output(self):
        step = _step(
            "logic.switch",
            quick_log=QuickLog(outputs=("vip",)),
            config={"rules": [{"name": "vip", "condition": "true"}]},
        )
        assert _problems(step) == []

    def test_a_step_whose_definition_is_gone_is_left_to_the_other_rules(self):
        step = _step("gone.step", quick_log=QuickLog(outputs=("out",)))
        assert _problems(step) == []

    @pytest.mark.parametrize(
        "message",
        ["{{step}} {{outcome}} {{error.code}} {{error.message}} {{to}} {{a.b.c}}", "no references"],
    )
    def test_a_message_may_read_the_step_the_outcome_the_output_and_the_error(self, message: str):
        assert _problems(_step(quick_log=QuickLog(message=message))) == []

    @pytest.mark.parametrize("definition_id", ["loop.item", "loop.yield"])
    def test_a_loops_item_and_yield_steps_take_no_quick_log(self, definition_id: str):
        step = _step(definition_id, quick_log=QuickLog())
        assert _problems(step) == [
            (
                f"nodes.{step.id}.quick_log",
                "A quick log goes on the loop itself, not on its item or yield step",
            )
        ]

    def test_an_empty_list_of_outputs_is_refused_where_unset_means_every_output(self):
        step = _step(quick_log=QuickLog(outputs=()))
        assert [field for field, _ in _problems(step)] == [f"nodes.{step.id}.quick_log.outputs"]

    @pytest.mark.parametrize(
        "reference", ["error.details", "error.details.token", "error", "error.retryable"]
    )
    def test_the_rest_of_an_error_is_refused(self, reference: str):
        step = _step(quick_log=QuickLog(message="Failed: {{" + reference + "}}"))
        (field, message), *rest = _problems(step)
        assert field == f"nodes.{step.id}.quick_log.message" and not rest
        assert reference in message

    def test_a_reference_with_no_value_on_some_run_is_not_a_problem(self):
        # Rendered empty when it has none: an output field of a failure, an error of a success.
        step = _step(quick_log=QuickLog(message="{{missing}} {{error.code}}", outputs=("true",)))
        assert _problems(step) == []


class TestReferences:
    def test_they_are_read_in_order_with_their_path(self):
        assert references("a {{ step }} b {{error.code}} {{x.y}} {{ }} {{9}} {x}") == (
            ("step",),
            ("error", "code"),
            ("x", "y"),
        )

    @pytest.mark.parametrize(
        ("path", "refused"),
        [
            (("error", "code"), False),
            (("error", "message"), False),
            (("error", "details"), True),
            (("error",), True),
            (("error", "code", "x"), True),
            (("step",), False),
            (("detail", "error"), False),
        ],
    )
    def test_only_the_code_and_message_of_an_error_may_be_read(
        self, path: tuple[str, ...], refused: bool
    ):
        assert refused_reference(path) is refused


class TestRendering:
    def _render(
        self,
        message: str,
        *,
        output: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> str:
        return render(
            message, step="Send mail", outcome="out", output=output, error=error, limit=2000
        )

    def test_the_default_message_names_the_step_and_where_it_went(self):
        assert self._render(DEFAULT_QUICK_LOG_MESSAGE) == "Send mail → out"

    def test_an_output_field_is_read_by_name_and_by_path(self):
        output = {"to": "ada@example.com", "result": {"id": 7, "tags": ["a", "b"]}}
        text = self._render("{{to}} {{ result.id }} {{result.tags}} {{result}}", output=output)
        assert text == 'ada@example.com 7 ["a","b"] {"id":7,"tags":["a","b"]}'

    def test_a_reference_with_no_value_renders_empty_and_never_raises(self):
        output = {"to": None, "result": "text"}
        text = self._render("[{{to}}][{{nope}}][{{result.id}}][{{a.b}}]", output=output)
        assert text == "[][][][]"

    def test_a_failed_step_reads_its_code_and_message_and_nothing_else(self):
        error = {"code": "SMTP_DOWN", "message": "Cannot reach the server", "details": {"k": "s"}}
        text = self._render(
            "{{error.code}}: {{error.message}} {{error.details}} {{error.details.k}}",
            output=None,
            error=error,
        )
        assert text == "SMTP_DOWN: Cannot reach the server  "

    def test_an_error_of_a_step_that_succeeded_renders_empty(self):
        assert self._render("[{{error.code}}]", output={"error": {"code": "X"}}) == "[]"

    def test_an_output_of_a_step_that_failed_renders_empty(self):
        assert self._render("[{{to}}]", output=None, error={"code": "X"}) == "[]"

    def test_a_large_output_is_cut_while_the_text_is_built(self):
        huge = ["x" * 100] * 1_000_000
        text = render(
            "a {{big}} b {{big}} {{to}}",
            step="s",
            outcome="o",
            output={"big": huge, "to": "y" * 50_000},
            error=None,
            limit=2000,
        )
        assert len(text) == 2000 and text.startswith('a ["xxxx')

    def test_the_rest_of_a_message_after_the_cap_is_dropped(self):
        text = render(
            "{{to}}{{step}}tail",
            step="s",
            outcome="o",
            output={"to": "y" * 10},
            error=None,
            limit=10,
        )
        assert text == "y" * 10

    def test_text_that_looks_like_a_reference_in_a_value_is_not_read_again(self):
        assert self._render("{{to}}", output={"to": "{{step}}"}) == "{{step}}"


def _run() -> Any:
    return SimpleNamespace(
        organization_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        id=uuid.uuid4(),
        mode=WorkflowRunMode.REAL.value,
    )


class TestTheWriter:
    async def test_a_step_whose_definition_was_removed_is_still_logged_under_its_kind(self):
        step = _step("gone.step", quick_log=QuickLog(message="{{step}} {{error.code}}"))
        graph = WorkflowGraph(entry_node_id=step.id, nodes=(step,))
        created = AsyncMock()
        with patch.object(writer.workflow_log_repo, "create", new=created):
            await writer.log_failed(
                AsyncMock(),
                run=_run(),
                graph=graph,
                node_run=SimpleNamespace(node_instance_id=step.id),
                error=WorkflowError(code="X", message="m", details={"k": "v"}),
                routed=True,
            )
        assert created.await_args.kwargs["step_label"] == "gone.step"
        assert created.await_args.kwargs["message"] == "gone.step X"

    @pytest.mark.parametrize(
        ("routed", "written"),
        [(False, 1), (True, 0)],
        ids=["a failure that is not routed ignores the filter", "a routed error follows it"],
    )
    async def test_the_outputs_filter_leaves_a_failure_that_is_not_routed_alone(
        self, routed: bool, written: int
    ):
        step = _step("gone.step", quick_log=QuickLog(outputs=("out",)))
        graph = WorkflowGraph(entry_node_id=step.id, nodes=(step,))
        created = AsyncMock()
        with patch.object(writer.workflow_log_repo, "create", new=created):
            await writer.log_failed(
                AsyncMock(),
                run=_run(),
                graph=graph,
                node_run=SimpleNamespace(node_instance_id=step.id),
                error=WorkflowError(code="X", message="m"),
                routed=routed,
            )
        assert created.await_count == written

    async def test_a_step_the_graph_does_not_have_writes_nothing(self):
        graph = WorkflowGraph(entry_node_id=(entry := _step()).id, nodes=(entry,))
        created = AsyncMock()
        node_run = SimpleNamespace(node_instance_id=uuid.uuid4())
        with patch.object(writer.workflow_log_repo, "create", new=created):
            await writer.log_failed(
                AsyncMock(),
                run=_run(),
                graph=graph,
                node_run=node_run,
                error=WorkflowError(code="X", message="m"),
                routed=False,
            )
            await writer.log_completed(
                AsyncMock(),
                run=_run(),
                graph=graph,
                node_run=node_run,
                definition=MagicMock(),
                output={},
                is_pinned=False,
            )
        created.assert_not_awaited()

    async def test_a_message_is_cut_to_what_a_line_may_hold(self):
        step = _step("logic.if", quick_log=QuickLog(message="{{big}}"))
        graph = WorkflowGraph(entry_node_id=step.id, nodes=(step,))
        created = AsyncMock()
        definitions = _resolve_definitions(graph)
        with patch.object(writer.workflow_log_repo, "create", new=created):
            await writer.log_completed(
                AsyncMock(),
                run=_run(),
                graph=graph,
                node_run=SimpleNamespace(node_instance_id=step.id),
                definition=definitions[step.id],
                output={"big": "x" * 5000, "condition": True},
                is_pinned=False,
            )
        assert len(created.await_args.kwargs["message"]) == 2000

    async def test_a_failure_with_no_graph_to_read_still_ends_the_run_and_writes_nothing(self):
        logged = AsyncMock()
        ended = AsyncMock()
        with (
            patch.object(dispatcher.quick_log, "log_failed", new=logged),
            patch.object(dispatcher, "_fail_node_and_run", new=ended),
        ):
            result = await dispatcher._fail_for_good(
                AsyncMock(),
                run=_run(),
                graph=None,
                node_run=SimpleNamespace(node_instance_id=uuid.uuid4()),
                error=WorkflowError(code="X", message="m"),
                now=MagicMock(),
            )
        assert result == []
        ended.assert_awaited_once()
        logged.assert_not_awaited()

    def test_an_entry_reads_as_its_step_and_outcome(self):
        entry = WorkflowLogEntry(step_label="Send", outcome="out", run_id=uuid.uuid4())
        assert repr(entry).startswith("<WorkflowLogEntry('Send' -> 'out'")


def test_a_run_prefix_with_wildcards_is_matched_literally():
    from sqlalchemy.dialects import postgresql

    from app.repositories.workflow_log_entry import _run_matches

    compiled = _run_matches("ab%_\\").compile(dialect=postgresql.dialect())
    assert "ESCAPE" in str(compiled)
    assert list(compiled.params.values()) == ["ab/%/_\\"]
