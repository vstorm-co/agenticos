"""The optional AgentDojo boundary uses real upstream tools without paid calls."""

import importlib.util
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

HERE = Path(__file__).resolve().parents[2] / "evals" / "agentdojo"


def test_optional_agentdojo_adapter_uses_upstream_runtime_and_scorer_without_paid_calls() -> None:
    pytest.importorskip("agentdojo")
    from agentdojo.functions_runtime import FunctionsRuntime
    from agentdojo.task_suite import get_suite

    adapter_spec = importlib.util.spec_from_file_location("assistant_agentdojo", HERE / "run.py")
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
