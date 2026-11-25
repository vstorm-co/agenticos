"""A code-mode script's calls on its `run_code` row, across a park and its resume.

The unit tests prove what reaches the repository; only a database says the
JSONB column holds the calls a parked segment wrote and the ones its resume
added, and that a recording built from the row offers each of them.
"""

import uuid

import pytest
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from sqlalchemy import select

from app.agents.code_checkpoint import ScriptCall
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.conversation import Conversation, ToolCall
from app.repositories import conversation as conversation_repo
from app.services.agent_runner import _answers_of
from app.services.transcript import RecordedToolCall, TranscriptService, script_calls_record
from tests.integration.test_transcript_savepoint import _org_and_agent, _owner

pytestmark = pytest.mark.anyio


def _made(n: int, tool: str) -> ScriptCall:
    return ScriptCall(
        call=ToolCallPart(tool, {"n": n}, tool_call_id=f"c9__{n}"),
        returned=ToolReturnPart(tool, f"{tool} {n}", tool_call_id=f"c9__{n}"),
    )


async def test_a_script_that_parks_twice_leaves_every_call_on_one_row(db) -> None:
    org, agent, version = await _org_and_agent(db)
    person = await _owner(db)
    conversation = Conversation(
        id=uuid.uuid4(), organization_id=org.id, user_id=person.id, title="Chat"
    )
    db.add(conversation)
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        conversation_id=conversation.id,
        status=RunStatus.COMPLETED.value,
        surface=RunSurface.API.value,
    )
    db.add(run)
    await db.flush()
    transcript = TranscriptService(db)

    await transcript.record(
        run,
        prompt="file and charge",
        answer="",
        tool_calls=[
            RecordedToolCall(
                tool_call_id="c9",
                tool_name="run_code",
                args={"code": "..."},
                script_calls=script_calls_record([_made(1, "file_ticket")]),
            ),
            RecordedToolCall(tool_call_id="c1", tool_name="notify", args={}, result="sent"),
        ],
        parked={"c9"},
    )
    await transcript.record(run, prompt=None, answer="", scripts={"c9": [_made(2, "charge")]})
    parked_again = (
        await db.execute(select(ToolCall).where(ToolCall.tool_call_id == "c9"))
    ).scalar_one()
    assert parked_again.completed_at is None
    assert parked_again.script_calls is not None
    assert len(parked_again.script_calls["calls"]) == 2
    await transcript.record(
        run,
        prompt=None,
        answer="done",
        settled={"c9": "[1, 2, 3]"},
        scripts={"c9": [_made(3, "notify")]},
    )

    rows = await conversation_repo.list_tool_calls_for_run(
        db, run_id=run.id, organization_id=org.id
    )
    assert sorted(row.tool_name for row, _turn in rows) == ["notify", "run_code"]
    plain = next(row for row, _turn in rows if row.tool_name == "notify")
    assert (plain.status, plain.result, plain.script_calls) == ("completed", "sent", None)
    (row,) = [row for row, _turn in rows if row.tool_name == "run_code"]
    stored = (await db.execute(select(ToolCall).where(ToolCall.id == row.id))).scalar_one()
    assert (stored.status, stored.result) == ("completed", "[1, 2, 3]")
    assert stored.script_calls is not None
    assert [call["tool_call_id"] for call in stored.script_calls["calls"]] == [
        "c9__1",
        "c9__2",
        "c9__3",
    ]
    assert [(answer.tool_name, answer.result) for answer in _answers_of(stored)] == [
        ("file_ticket", "file_ticket 1"),
        ("charge", "charge 2"),
        ("notify", "notify 3"),
    ]
