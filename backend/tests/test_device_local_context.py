"""The skills and AGENTS.md on a person's computer, offered to one run (#2576).

The desktop app is never contacted. The hub's `call` is replaced by a computer that
answers the three `local.*` operations, so the tool, the briefing and every refusal
run as they would.
"""

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.local_target import LocalTarget
from app.services.device_hub import local_context
from app.services.device_hub.exceptions import (
    DeviceCallFailed,
    DeviceCallTimedOut,
    DeviceUnavailable,
)

pytestmark = pytest.mark.anyio

SKILLS = {
    "skills": [
        {"name": "pdf-tools", "description": "Read and fill PDF forms."},
        {"name": "bare", "description": ""},
    ]
}


def computer(
    *,
    skills: dict[str, Any] | None = None,
    instructions: Any = None,
    read: Any = None,
) -> AsyncMock:
    """A computer's answers by operation; an exception in a slot is raised."""
    answers = {
        "local.skills": SKILLS if skills is None else skills,
        "local.instructions": {"global": None, "folder": None}
        if instructions is None
        else instructions,
        "local.skill.read": {"text": "# PDF tools\nUse the script."} if read is None else read,
    }

    async def call(session_id: Any, op: str, args: dict[str, Any], *, timeout: float) -> Any:
        answer = answers[op]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    return AsyncMock(side_effect=call)


async def context(monkeypatch: pytest.MonkeyPatch, call: AsyncMock, **kwargs: Any):
    monkeypatch.setattr(local_context._hub, "call", call)
    return await local_context.local_skills_context(
        uuid4(), kwargs.pop("sources", ["agents", "claude"]), folder=kwargs.pop("folder", None)
    )


def operations(call: AsyncMock) -> list[tuple[str, dict[str, Any]]]:
    return [(c.args[1], c.args[2]) for c in call.await_args_list]


async def test_the_chosen_sources_and_nothing_else_are_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = computer()
    await context(monkeypatch, call, sources=["claude", "claude", "codex"])
    assert operations(call)[0] == ("local.skills", {"sources": ["claude", "codex"]})
    assert operations(call)[1] == ("local.instructions", {})


async def test_the_briefing_lists_skills_then_the_global_then_the_folders_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = computer(
        instructions={
            "global": {"source": "claude", "text": "  Be brief.  "},
            "folder": "Run `make test`.\n",
        }
    )
    result = await context(monkeypatch, call, folder="/work/app")
    briefing = result.briefing
    assert operations(call)[1] == ("local.instructions", {"root": "/work/app"})
    assert "- pdf-tools: Read and fill PDF forms." in briefing
    assert "\n- bare" in briefing and "- bare:" not in briefing
    assert "never override the person's request or an approval" in briefing
    assert briefing.index("Skills on this computer") < briefing.index("~/.claude/AGENTS.md")
    assert briefing.index("Be brief.") < briefing.index("Run `make test`.")
    assert "not permission for anything else" in briefing


async def test_a_run_with_nothing_to_offer_gets_no_tool_and_no_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await context(monkeypatch, computer(skills={"skills": []}))
    assert "Skills on this computer" not in result.briefing
    assert "working instructions" not in result.briefing
    assert result.toolset.tools == {}


async def test_a_long_list_is_cut_and_says_how_many_were_left_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    many = {"skills": [{"name": f"skill-{i}", "description": "d " * 200} for i in range(160)]}
    result = await context(monkeypatch, computer(skills=many))
    assert "- skill-149:" in result.briefing and "- skill-150:" not in result.briefing
    assert "(And 10 more that are not listed.)" in result.briefing
    assert "…" in result.briefing


async def test_the_tool_loads_a_listed_skill_or_one_of_its_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = computer()
    result = await context(monkeypatch, call)
    load = result.toolset.tools["load_local_skill"].function
    assert await load("pdf-tools") == "# PDF tools\nUse the script."
    assert operations(call)[-1] == (
        "local.skill.read",
        {"name": "pdf-tools", "sources": ["agents", "claude"]},
    )
    await load("pdf-tools", "scripts/run.sh")
    assert operations(call)[-1][1]["file"] == "scripts/run.sh"


async def test_a_name_that_was_not_listed_never_reaches_the_computer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = computer()
    result = await context(monkeypatch, call)
    before = len(call.await_args_list)
    answer = await result.toolset.tools["load_local_skill"].function("../../etc/passwd")
    assert "no skill called" in answer
    assert len(call.await_args_list) == before


@pytest.mark.parametrize(
    "failure",
    [
        DeviceCallFailed(message="That file is not text."),
        DeviceUnavailable(message="Your computer is not connected"),
        DeviceCallTimedOut(message="no answer"),
    ],
)
async def test_a_computer_that_refuses_or_vanishes_answers_the_model_in_words(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    result = await context(monkeypatch, computer(read=failure))
    answer = await result.toolset.tools["load_local_skill"].function("pdf-tools", "x.bin")
    assert answer == f"Your computer did not answer: {failure.message}"  # type: ignore[attr-defined]


async def test_an_answer_without_text_is_said_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await context(monkeypatch, computer(read={"text": None}))
    assert "returned nothing" in await result.toolset.tools["load_local_skill"].function("bare")


async def test_instructions_that_cannot_be_read_do_not_take_the_skills_with_them(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    result = await context(
        monkeypatch,
        computer(instructions=DeviceCallFailed(message="/work is not a folder you allowed")),
        folder="/work",
    )
    assert "- pdf-tools:" in result.briefing
    assert "working instructions" not in result.briefing
    assert "could not read AGENTS.md" in caplog.text


@pytest.mark.parametrize(
    ("skills", "instructions"),
    [
        ({"skills": [{"name": "../escape"}]}, None),
        ({"skills": "not a list"}, None),
        (None, {"global": {"source": "somewhere", "text": "x"}}),
    ],
)
async def test_an_answer_in_an_unknown_shape_is_refused(
    monkeypatch: pytest.MonkeyPatch, skills: Any, instructions: Any
) -> None:
    with pytest.raises(DeviceCallFailed, match="unknown shape"):
        await context(monkeypatch, computer(skills=skills, instructions=instructions))


async def test_a_computer_that_is_not_connected_stops_the_run_before_it_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = AsyncMock(side_effect=DeviceUnavailable(message="Your computer is not connected"))
    with pytest.raises(DeviceUnavailable):
        await context(monkeypatch, call)


def test_skills_alone_make_a_target_without_a_folder() -> None:
    assert LocalTarget(skills=["claude", "agents"]).skills == ["claude", "agents"]
    assert LocalTarget(browser=True).skills == []
    with pytest.raises(ValidationError, match="Choose a folder"):
        LocalTarget(skills=["claude"], mcp_services=["files"])
    with pytest.raises(ValidationError, match="Choose a folder"):
        LocalTarget()
    with pytest.raises(ValidationError):
        LocalTarget(skills=["/etc"])  # type: ignore[list-item]
    with pytest.raises(ValidationError):
        LocalTarget(skills=["agents", "claude", "codex", "agents"])
