"""The model steps' own logic around a stubbed request: prompts, ports and refusals.

A real runner and model are `tests/integration/test_workflow_model_steps.py`'s;
these pin what each step asks for, what it makes of the answer, and the
configurations it refuses.
"""

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun, RunStatus
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed
from app.workflows.nodes import _model_step
from app.workflows.nodes.ai_classify import _handler as classify
from app.workflows.nodes.ai_extract import _handler as extract
from app.workflows.nodes.ai_prompt import _handler as prompt
from app.workflows.nodes.ai_rewrite import _handler as rewrite

pytestmark = pytest.mark.anyio

MODEL = str(uuid.uuid4())


def _dispatch(*, in_workflow: bool = True) -> context.DispatchContext:
    org = uuid.uuid4()
    return context.DispatchContext(
        organization_id=org,
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=AuthContext(user_id=uuid.uuid4(), organization_id=org, role="owner"),
        resumed_agent_run_id=None,
        workflow_id=uuid.uuid4() if in_workflow else None,
    )


def _answer(text: str = "ok", structured: dict[str, Any] | None = None):
    return _model_step.Answer(text=text, structured=structured, agent_run_id=uuid.uuid4())


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """The request every model step makes, stubbed: what it was asked, and its answer."""
    stub = AsyncMock(return_value=_answer())
    monkeypatch.setattr(_model_step, "ask", stub)
    return stub


async def _run(handler: Any, config: Any, node_input: Any):
    with context.dispatching_as(_dispatch()):
        return await handler.handle(config, node_input)


class TestAskAModel:
    async def test_it_asks_with_the_steps_instructions_and_hands_on_the_text(self, asked):
        asked.return_value = _answer("Warm lead.")
        config = prompt.AiPromptConfig(model_profile_id=MODEL, instructions="Score leads.")

        result = await _run(prompt, config, prompt.AiPromptInput(prompt="Acme, 500 seats"))

        assert isinstance(result, Completed) and result.output.text == "Warm lead."
        spec: AgentSpec = asked.await_args.args[1]
        assert spec.instructions == "Score leads." and spec.output_schema is None
        assert spec.capabilities == [] and spec.mcp_servers == []
        assert asked.await_args.args[2] == "Acme, 500 seats"

    async def test_a_schema_asks_for_an_object_and_text_instead_fails(self, asked):
        schema = {"type": "object", "properties": {"score": {"type": "integer"}}}
        config = prompt.AiPromptConfig(model_profile_id=MODEL, structured_output_schema=schema)

        result = await _run(prompt, config, prompt.AiPromptInput(prompt="x"))

        assert asked.await_args.args[1].output_schema == schema
        assert isinstance(result, Failed) and result.error.code == "STRUCTURED_OUTPUT_MISMATCH"

    async def test_with_no_instructions_it_is_told_to_answer(self, asked):
        await _run(
            prompt, prompt.AiPromptConfig(model_profile_id=MODEL), prompt.AiPromptInput(prompt="x")
        )
        assert asked.await_args.args[1].instructions == "Answer the prompt."


class TestClassify:
    CONFIG = classify.AiClassifyConfig(
        model_profile_id=MODEL,
        categories=(
            classify.Category(name="sales", description="Wants to buy"),
            classify.Category(name="support", description="Needs help"),
        ),
        instructions="Prefer support on a tie.",
    )

    async def test_it_branches_on_the_category_the_model_chose(self, asked):
        asked.return_value = _answer(structured={"category": "support", "reason": "A bug"})

        result = await _run(classify, self.CONFIG, classify.AiClassifyInput(text="It crashes"))

        assert isinstance(result, Completed)
        assert (result.output.category, result.output.reason, result.output.text) == (
            "support",
            "A bug",
            "It crashes",
        )
        assert classify.routes(result.output.model_dump()) == frozenset({"support"})

    async def test_the_model_may_only_answer_with_a_category_or_other(self, asked):
        spec: AgentSpec
        await _run(classify, self.CONFIG, classify.AiClassifyInput(text="x"))
        spec = asked.await_args.args[1]
        assert spec.output_schema is not None
        assert spec.output_schema["properties"]["category"]["enum"] == ["sales", "support", "other"]
        assert "- sales: Wants to buy" in spec.instructions
        assert spec.instructions.endswith("Prefer support on a tie.")

    async def test_an_invented_category_fails_rather_than_taking_no_branch(self, asked):
        asked.return_value = _answer(structured={"category": "billing", "reason": "?"})

        result = await _run(classify, self.CONFIG, classify.AiClassifyInput(text="x"))

        assert isinstance(result, Failed) and result.error.code == "STRUCTURED_OUTPUT_MISMATCH"

    def test_a_port_per_category_then_other(self):
        assert [port.id for port in classify.ports_for(self.CONFIG)] == [
            "in",
            "sales",
            "support",
            "other",
        ]
        assert [port.id for port in classify.ports_for(None)] == ["in", "other"]
        assert classify.routes(None) == frozenset()

    def test_categories_must_be_distinct_and_not_reserved(self):
        for names in (("a", "a"), ("other",), ("in",)):
            with pytest.raises(ValidationError):
                classify.AiClassifyConfig(
                    model_profile_id=MODEL,
                    categories=tuple(classify.Category(name=n, description="d") for n in names),
                )


class TestExtract:
    SCHEMA = {"type": "object", "properties": {"total": {"type": "number"}}}

    async def test_it_hands_on_the_object_extracted(self, asked):
        asked.return_value = _answer(structured={"total": 12.5})
        config = extract.AiExtractConfig(
            model_profile_id=MODEL, output_schema=self.SCHEMA, instructions="Totals in EUR."
        )

        result = await _run(extract, config, extract.AiExtractInput(text="Total: 12.50 EUR"))

        assert isinstance(result, Completed) and result.output.data == {"total": 12.5}
        spec = asked.await_args.args[1]
        assert spec.output_schema == self.SCHEMA
        assert "never guess" in spec.instructions and spec.instructions.endswith("Totals in EUR.")

    async def test_text_instead_of_the_fields_fails(self, asked):
        config = extract.AiExtractConfig(model_profile_id=MODEL, output_schema=self.SCHEMA)
        result = await _run(extract, config, extract.AiExtractInput(text="x"))
        assert isinstance(result, Failed) and result.error.code == "STRUCTURED_OUTPUT_MISMATCH"

    def test_a_schema_that_is_not_one_is_refused(self):
        with pytest.raises(ValidationError):
            extract.AiExtractConfig(model_profile_id=MODEL, output_schema={"type": "nonsense"})


class TestRewrite:
    @pytest.mark.parametrize(
        ("settings", "expected"),
        [
            ({"task": "summarize", "length": "short"}, "Summarize the text you are given in two"),
            (
                {"task": "translate", "language": "Polish"},
                "Translate the text you are given into Polish",
            ),
            (
                {"task": "rewrite", "language": "German", "style": "formal"},
                "Answer in German. Style: formal.",
            ),
        ],
    )
    async def test_the_settings_become_the_instructions(self, asked, settings, expected):
        asked.return_value = _answer("Done.")
        config = rewrite.AiRewriteConfig(model_profile_id=MODEL, **settings)

        result = await _run(rewrite, config, rewrite.AiRewriteInput(text="Long text"))

        assert isinstance(result, Completed) and result.output.text == "Done."
        assert expected in asked.await_args.args[1].instructions

    def test_a_translation_needs_a_language(self):
        with pytest.raises(ValidationError, match="which language"):
            rewrite.AiRewriteConfig(model_profile_id=MODEL, task="translate")


@pytest.mark.parametrize(
    ("handler", "config", "node_input"),
    [
        (prompt, prompt.AiPromptConfig(model_profile_id=MODEL), prompt.AiPromptInput(prompt="x")),
        (
            classify,
            TestClassify.CONFIG,
            classify.AiClassifyInput(text="x"),
        ),
        (
            extract,
            extract.AiExtractConfig(model_profile_id=MODEL, output_schema=TestExtract.SCHEMA),
            extract.AiExtractInput(text="x"),
        ),
        (
            rewrite,
            rewrite.AiRewriteConfig(model_profile_id=MODEL),
            rewrite.AiRewriteInput(text="x"),
        ),
    ],
)
class TestEveryModelStep:
    async def test_a_failed_request_fails_the_step(self, asked, handler, config, node_input):
        asked.return_value = Failed(error=_model_step.WorkflowError(code="X", message="no"))
        result = await _run(handler, config, node_input)
        assert isinstance(result, Failed) and result.error.code == "X"

    async def test_without_its_settings_it_says_so(self, handler, config, node_input):
        result = await handler.handle(None, None)
        assert isinstance(result, Failed) and result.error.code == "MODEL_STEP_NOT_CONFIGURED"

    async def test_publishing_checks_the_spec_it_would_run(
        self, monkeypatch, handler, config, node_input
    ):
        service = MagicMock(problems=AsyncMock(return_value=["No access to this model"]))
        monkeypatch.setattr(_model_step, "WorkflowAgentService", lambda _db: service)

        problems = await handler.check_resources(MagicMock(), _dispatch().auth, config)

        assert problems == [("model_profile_id", "No access to this model")]
        assert await handler.check_resources(MagicMock(), _dispatch().auth, MagicMock()) == []


class TestTheRequest:
    """`_model_step.ask` itself, around a stubbed service and runner."""

    @pytest.fixture
    def runner(self, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
        stub = MagicMock(execute=AsyncMock())
        service = MagicMock(version_for=AsyncMock(return_value=(uuid.uuid4(), uuid.uuid4())))

        @asynccontextmanager
        async def session():
            yield MagicMock()

        monkeypatch.setattr(_model_step, "get_worker_db_context", session)
        monkeypatch.setattr(_model_step, "AgentRunnerService", lambda _db: stub)
        monkeypatch.setattr(_model_step, "WorkflowAgentService", lambda _db: service)
        return stub

    @staticmethod
    def _run_row(status: RunStatus, *, cost: str = "0.01", partial: bool = False):
        return SimpleNamespace(
            id=uuid.uuid4(),
            status=status.value,
            cost_usd=Decimal(cost),
            cost_is_partial=partial,
            error=None,
        )

    async def test_it_runs_the_steps_agent_and_books_the_cost(self, runner):
        runner.execute.return_value = ("hi", self._run_row(RunStatus.COMPLETED))
        config = prompt.AiPromptConfig(model_profile_id=MODEL, max_cost_usd=0.2)

        with context.dispatching_as(_dispatch()) as scope:
            answer = await _model_step.ask(config, AgentSpec(name="x"), "go")

        assert isinstance(answer, _model_step.Answer) and answer.text == "hi"
        assert scope.cost == Decimal("0.01")
        assert runner.execute.await_args.kwargs["run_limit_usd"] == Decimal("0.2")

    async def test_a_run_that_did_not_complete_fails_with_its_code(self, runner):
        runner.execute.return_value = ("", self._run_row(RunStatus.BUDGET_EXCEEDED, cost="0"))
        config = prompt.AiPromptConfig(model_profile_id=MODEL)

        with context.dispatching_as(_dispatch()):
            answer = await _model_step.ask(config, AgentSpec(name="x"), "go")

        assert isinstance(answer, Failed) and answer.error.code == "AGENT_BUDGET_EXCEEDED"
        assert runner.execute.await_args.kwargs["run_limit_usd"] is None

    async def test_a_refusal_is_passed_through_and_an_error_says_nothing_of_the_provider(
        self, runner
    ):
        config = prompt.AiPromptConfig(model_profile_id=MODEL)
        runner.execute.side_effect = BadRequestError(message="No model selected")
        with context.dispatching_as(_dispatch()):
            refused = await _model_step.ask(config, AgentSpec(name="x"), "go")
        runner.execute.side_effect = RuntimeError("https://api.example.com/?key=sk-123")
        with context.dispatching_as(_dispatch()):
            broken = await _model_step.ask(config, AgentSpec(name="x"), "go")

        assert isinstance(refused, Failed) and refused.error.message == "No model selected"
        assert isinstance(broken, Failed) and "sk-123" not in broken.error.message

    async def test_outside_a_workflow_it_refuses(self, runner):
        with context.dispatching_as(_dispatch(in_workflow=False)):
            answer = await _model_step.ask(
                prompt.AiPromptConfig(model_profile_id=MODEL), AgentSpec(name="x"), "go"
            )
        assert isinstance(answer, Failed) and answer.error.code == "MODEL_STEP_OUTSIDE_WORKFLOW"
        runner.execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (RunStatus.COMPLETED, None),
        (RunStatus.GUARDRAIL_BLOCKED, "AGENT_GUARDRAIL_BLOCKED"),
        (RunStatus.FAILED, "AGENT_RUN_FAILED"),
    ],
)
def test_an_agent_runs_ending_is_read_the_same_by_every_step(status, code):
    run = SimpleNamespace(id=uuid.uuid4(), status=status.value, error=None)
    failed = _model_step.outcome(cast(AgentRun, run))
    assert (failed.error.code if failed else None) == code
