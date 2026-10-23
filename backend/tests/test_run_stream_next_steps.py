"""Next steps a model of their own wrote, sent as the agent's own call would be (#2301).

The console draws next steps from a `suggest_next_steps` call and the transcript
keeps them from it, so steps written after the answer by the follow-ups model
are sent and collected as exactly that call - and nothing is sent without them.
"""

import json
from typing import Any

import pytest

from app.agents.deps import AgentDeps, WrittenNextSteps
from app.services.run_stream import RunFrames

pytestmark = pytest.mark.anyio


def _frames() -> tuple[RunFrames, list[tuple[str, dict[str, Any]]]]:
    sent: list[tuple[str, dict[str, Any]]] = []

    async def emit(kind: str, data: dict[str, Any]) -> None:
        sent.append((kind, data))

    return RunFrames(emit=emit), sent


async def test_written_steps_are_sent_and_kept_as_the_call() -> None:
    frames, sent = _frames()
    deps = AgentDeps(next_steps=WrittenNextSteps(call_id="next_steps_1", steps=["Zrób tabelę"]))

    await frames.next_steps(deps)

    assert [kind for kind, _ in sent] == ["tool_call", "tool_result"]
    assert sent[0][1] == {
        "tool_call_id": "next_steps_1",
        "tool_name": "suggest_next_steps",
        "args": {"steps": ["Zrób tabelę"]},
    }
    assert json.loads(sent[1][1]["content"]) == {"steps": ["Zrób tabelę"]}
    assert frames.tool_calls[0]["result"] == sent[1][1]["content"]


@pytest.mark.parametrize("deps", [AgentDeps(), None])
async def test_nothing_is_sent_without_written_steps(deps: object) -> None:
    frames, sent = _frames()

    await frames.next_steps(deps)

    assert sent == []
    assert frames.tool_calls == []
