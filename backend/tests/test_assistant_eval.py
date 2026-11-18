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
