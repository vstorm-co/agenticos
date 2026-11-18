"""Run AgentDojo's official workspace utility tasks with the shipped prompt.

Optional eval-only dependency: agentdojo==0.1.35. This adapter evaluates template
instructions with AgentDojo's simulated tools and official state-based scorer,
not a deployed AgenticOS agent, approvals, vault or native coding containers.
"""

import argparse
import hashlib
import importlib.metadata
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import JsonValue, TypeAdapter
from pydantic_ai import Agent, Tool
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits
from pydantic_core import to_jsonable_python

from app.services.agent_templates import STARTER_TEMPLATE, get

if TYPE_CHECKING:
    from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement


@dataclass(frozen=True)
class AgentDojoAdapter:
    pipeline: BasePipelineElement
    usage: dict[str, int]


AGENTDOJO_VERSION = "0.1.35"
BENCHMARK_VERSION = "v1.2.2"
JSON_ARGUMENTS = TypeAdapter(dict[str, JsonValue])


def pipeline(model: str | Model, instructions: str) -> AgentDojoAdapter:
    """Adapt only the optional benchmark boundary; production imports none of it."""
    from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
    from agentdojo.functions_runtime import (
        EmptyEnv,
        FunctionCall,
        FunctionsRuntime,
        TaskEnvironment,
    )
    from agentdojo.types import ChatMessage

    usage: dict[str, int] = {}

    class Pipeline(BasePipelineElement):
        name = "agenticos-template-" + hashlib.sha256(instructions.encode()).hexdigest()[:12]

        def query(
            self,
            query: str,
            runtime: FunctionsRuntime,
            env: TaskEnvironment | None = None,
            messages: Sequence[ChatMessage] = (),
            extra_args: dict[str, object] | None = None,
        ) -> tuple[
            str, FunctionsRuntime, TaskEnvironment, Sequence[ChatMessage], dict[str, object]
        ]:
            if messages:
                raise ValueError("This utility adapter expects an independent AgentDojo task")
            environment = env if env is not None else EmptyEnv()
            transcript: list[ChatMessage] = [
                {"role": "user", "content": [{"type": "text", "content": query}]}
            ]

            def execute(name: str) -> Callable[..., str]:
                def call(**arguments: object) -> str:
                    parsed = JSON_ARGUMENTS.validate_python(arguments)
                    invocation = FunctionCall(
                        function=name, args=parsed, id=f"eval-{len(transcript)}"
                    )
                    result, error = runtime.run_function(environment, name, parsed)
                    text = error if error is not None else json.dumps(to_jsonable_python(result))
                    transcript.append(
                        {"role": "assistant", "content": None, "tool_calls": [invocation]}
                    )
                    transcript.append(
                        {
                            "role": "tool",
                            "tool_call": invocation,
                            "tool_call_id": invocation.id,
                            "error": error,
                            "content": [{"type": "text", "content": text}],
                        }
                    )
                    return text

                return call

            tools = [
                Tool.from_schema(
                    execute(name),
                    name,
                    function.description,
                    function.parameters.model_json_schema(),
                    sequential=True,
                )
                for name, function in runtime.functions.items()
            ]
            agent = Agent(model, instructions=instructions, tools=tools)
            result = agent.run_sync(
                query,
                usage_limits=UsageLimits(
                    request_limit=20,
                    tool_calls_limit=30,
                    total_tokens_limit=100_000,
                ),
            )
            transcript.append(
                {
                    "role": "assistant",
                    "tool_calls": None,
                    "content": [{"type": "text", "content": result.output}],
                }
            )
            usage.clear()
            usage.update(result.usage.opentelemetry_attributes())
            return query, runtime, environment, transcript, extra_args or {}

    return AgentDojoAdapter(Pipeline(), usage)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    parser.add_argument("--run", action="store_true", help="make real, billable model calls")
    parser.add_argument("--task", action="append", default=[])
    parser.add_argument("--output", type=Path, default=Path("agentdojo-eval.json"))
    args = parser.parse_args()
    tasks = args.task or ["user_task_0", "user_task_1"]
    if len(tasks) > 10 or any(not re.fullmatch(r"user_task_[0-9]+", task) for task in tasks):
        parser.error("Choose at most ten explicit user_task_N IDs per invocation")
    template = get(STARTER_TEMPLATE)
    if template is None:
        raise RuntimeError("The shipped AgenticOS template is unavailable")
    identity = {
        "benchmark": "AgentDojo",
        "package_version": AGENTDOJO_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "suite": "workspace",
        "template_sha256": hashlib.sha256(template.instructions.encode()).hexdigest(),
        "model": args.model,
        "tasks": tasks,
        "mode": "utility_without_injections",
    }
    if not args.run:
        print(json.dumps({"plan": identity, "model_calls": 0}, indent=2))
        return
    if not args.model:
        parser.error("--run needs an explicit --model")
    if importlib.metadata.version("agentdojo") != AGENTDOJO_VERSION:
        parser.error(f"Use the documented eval-only agentdojo=={AGENTDOJO_VERSION} environment")
    from agentdojo.task_suite import get_suite

    suite = get_suite(BENCHMARK_VERSION, "workspace")
    # Validate every task before spending on any of them.
    selected = [suite.get_user_task_by_id(task) for task in tasks]
    adapter = pipeline(args.model, template.instructions)
    results: list[dict[str, object]] = []
    for task in selected:
        try:
            utility, _ = suite.run_task_with_pipeline(adapter.pipeline, task, None, {})
            results.append({"task": task.ID, "utility": utility, "usage": dict(adapter.usage)})
        except Exception as error:
            # An unavailable provider is a failed task, never an omitted task.
            results.append({"task": task.ID, "utility": False, "error": type(error).__name__})
    args.output.write_text(
        json.dumps({**identity, "at": datetime.now(UTC).isoformat(), "results": results}, indent=2)
        + "\n"
    )
    print(f"Wrote {args.output}")
    if any(not result["utility"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
