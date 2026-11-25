"""What a code-mode script called, where it is captured and read beyond the transcript.

The model calls one tool, `run_code`; the agent's real tools are called by the
script. Everything that judges an answer by its calls reads the script's calls.
"""

import uuid
from dataclasses import fields
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai_harness.code_mode._toolset import RunCodeExecution

from app.agents.code_checkpoint import ScriptCall
from app.agents.deps import AgentDeps
from app.core.permissions import AuthContext, OrgRoleName
from app.services import dataset as dataset_module
from app.services.dataset import DatasetService
from app.services.run_stream import RunFrames

pytestmark = pytest.mark.anyio


def test_the_pinned_harness_still_keeps_a_scripts_calls_where_capture_reads_them() -> None:
    """Capture reads private state of `pydantic-ai-harness`: its per-script call maps and
    the `<run_code id>__<n>` ids. An upgrade that moves either fails here, not in an eval."""
    execution = RunCodeExecution(parent_tool_call_id="c9")

    assert execution.next_tool_call_id(max_tool_calls=5) == "c9__1"
    assert {"nested_calls", "nested_returns", "nested_errors"} <= {
        field.name for field in fields(execution)
    }


def _entry(tool: str, outcome: str) -> dict[str, Any]:
    return {
        "tool_call_id": f"c9__{tool}",
        "tool_name": tool,
        "args": {},
        "result": "r",
        "outcome": outcome,
    }


async def test_a_case_drafted_from_a_code_mode_reply_expects_what_its_script_did(
    monkeypatch,
) -> None:
    """Drafted as `run_code`, the case would fail every later answer that graded the
    script's calls in its place."""
    rows = [
        MagicMock(
            tool_name="run_code",
            status="completed",
            script_calls={
                "calls": [
                    _entry("create_ticket", "success"),
                    _entry("charge_card", "failed"),
                    _entry("send_email", "denied"),
                ],
                "omitted": 0,
            },
        ),
        MagicMock(tool_name="notify", status="completed", script_calls=None),
        MagicMock(tool_name="retry", status="failed", script_calls=None),
    ]
    monkeypatch.setattr(
        dataset_module.conversation_repo, "tool_calls_of_messages", AsyncMock(return_value=rows)
    )
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)

    expected = await DatasetService(AsyncMock())._expected_calls(ctx, None, [MagicMock()])

    assert expected == ["create_ticket", "notify"]


class _Ended:
    """An agent run that has already ended, or that ends by raising."""

    def __init__(self, deps: AgentDeps, *, failure: Exception | None = None) -> None:
        self.ctx = SimpleNamespace(deps=SimpleNamespace(user_deps=deps))
        self.failure = failure

    def __aiter__(self) -> _Ended:
        return self

    async def __anext__(self) -> None:
        if self.failure is not None:
            raise self.failure
        raise StopAsyncIteration


def _settled(parent: str) -> ScriptCall:
    return ScriptCall(
        call=ToolCallPart("lookup", {"q": 1}, tool_call_id=f"{parent}__1"),
        returned=ToolReturnPart("lookup", "found", tool_call_id=f"{parent}__1"),
    )


@pytest.mark.parametrize("failure", [None, RuntimeError("socket gone")])
async def test_a_streamed_script_keeps_its_calls_however_the_run_ended(failure) -> None:
    """A script parked on an approval has no result frame, and still keeps what it did."""
    deps = AgentDeps()
    deps.code_continuations.script_calls["c9"] = [_settled("c9")]
    frames = RunFrames(emit=AsyncMock())
    frames.tool_calls.extend(
        [
            {"tool_call_id": "c9", "tool_name": "run_code", "args": {}},
            {"tool_call_id": "c2", "tool_name": "notify", "args": {}},
        ]
    )

    if failure is None:
        await frames.drive(_Ended(deps))
    else:
        with pytest.raises(RuntimeError):
            await frames.drive(_Ended(deps, failure=failure))

    script, plain = frames.tool_calls
    assert [entry["tool_name"] for entry in script["script_calls"]["calls"]] == ["lookup"]
    assert "script_calls" not in plain
