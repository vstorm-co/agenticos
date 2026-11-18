"""Smoke eval arithmetic and execution are verified offline, not model quality."""

import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

HERE = Path(__file__).resolve().parents[2] / "evals" / "assistant"
spec = importlib.util.spec_from_file_location("assistant_evaluation", HERE / "evaluation.py")
assert spec is not None and spec.loader is not None
evaluation = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = evaluation
spec.loader.exec_module(evaluation)


def test_a_greeting_must_be_short_natural_and_without_unrequested_tools() -> None:
    case = evaluation.load_cases(HERE / "cases.json")[0]
    assert evaluation.evaluate(case, "Siema!", []).passed
    assert not evaluation.evaluate(case, "SIEM stands for security information...", []).passed
    assert not evaluation.evaluate(case, "Hej " * 100, []).passed
    assert not evaluation.evaluate(
        case, "Hej!", [evaluation.Call(name="read_web_page", arguments={})]
    ).passed


def test_retries_and_named_sessions_are_scored_with_multiplicity() -> None:
    cases = {case.id: case for case in evaluation.load_cases(HERE / "cases.json")}
    case = cases["safe-read-retry"]
    call = evaluation.Call(name="read_web_page", arguments={"url": "https://example.test/status"})
    assert not evaluation.evaluate(case, "healthy", [call]).passed
    assert evaluation.evaluate(case, "healthy", [call, call]).passed
    coding = cases["named-coding-session-continuation"]
    calls = [
        evaluation.Call(name="run_coding_agent", arguments={"harness": harness, "session": name})
        for harness, name in coding.coding_sessions
    ]
    assert evaluation.evaluate(coding, "Completed", calls).passed
    calls[-1].arguments["harness"] = "claude_code"
    assert not evaluation.evaluate(coding, "Completed", calls).passed
    calls[0].arguments["harness"] = {}
    assert not evaluation.evaluate(coding, "Completed", calls).passed


@pytest.mark.anyio
async def test_model_execution_can_be_exercised_without_any_paid_provider(monkeypatch) -> None:
    # The CLI imports its sibling by name, so expose only that one during import.
    monkeypatch.setitem(sys.modules, "evaluation", evaluation)
    run_spec = importlib.util.spec_from_file_location("assistant_eval_run", HERE / "run.py")
    assert run_spec is not None and run_spec.loader is not None
    runner = importlib.util.module_from_spec(run_spec)
    run_spec.loader.exec_module(runner)
    case = evaluation.Case(id="hello", prompt="hi", required_any=["Hello"], max_calls=0)
    result = await runner.run_case(
        case, TestModel(call_tools=[], custom_output_text="Hello"), "Be helpful"
    )
    assert result.verdict.passed and result.calls == []


def test_optional_agentdojo_adapter_uses_upstream_runtime_and_scorer_without_paid_calls() -> None:
    pytest.importorskip("agentdojo")
    from agentdojo.functions_runtime import FunctionsRuntime
    from agentdojo.task_suite import get_suite

    adapter_spec = importlib.util.spec_from_file_location(
        "assistant_agentdojo", HERE / "agentdojo_eval.py"
    )
    assert adapter_spec is not None and adapter_spec.loader is not None
    adapter_module = importlib.util.module_from_spec(adapter_spec)
    adapter_spec.loader.exec_module(adapter_module)
    runtime = FunctionsRuntime([])
    received: list[tuple[int, int]] = []

    @runtime.register_function
    def add(x: int, y: int) -> int:
        """Add two numbers.

        :param x: The first number.
        :param y: The second number.
        """
        received.append((x, y))
        return x + y

    adapter = adapter_module.pipeline(
        TestModel(call_tools=["add"], custom_output_text="Done"), "Be helpful"
    )
    _, _, _, transcript, _ = adapter.pipeline.query("Add two numbers", runtime)
    assert len(received) == 1
    assert transcript[-1]["content"][0]["content"] == "Done"
    assert [message["role"] for message in transcript] == ["user", "assistant", "tool", "assistant"]
    assert transcript[1]["tool_calls"][0].function == "add"
    assert adapter.usage
    suite = get_suite(adapter_module.BENCHMARK_VERSION, "workspace")
    no_tools = adapter_module.pipeline(
        TestModel(call_tools=[], custom_output_text="Unknown"), "Be helpful"
    )
    utility, _ = suite.run_task_with_pipeline(
        no_tools.pipeline, suite.get_user_task_by_id("user_task_0"), None, {}
    )
    assert utility is False
