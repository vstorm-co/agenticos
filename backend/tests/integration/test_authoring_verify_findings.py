"""Verify's findings, each tied to the line of the edit it is about.

Every quote is checked against the run it names, but whether a quote bears on a
finding is not something a check can decide - a weak model backed "Greet the
customer by name" with a real quote about gift wrapping. So a finding names the
line it is about, that line must be part of the edit, and a finding that the
edit is supported with no checkable quote left is not shown at all.
"""

import pytest

from app.services.authoring import AuthoringService
from tests.integration.test_authoring import (
    COMMENT,
    Improver,
    _environment,  # noqa: F401 - the autouse fixture that scripts the improver's model
    _improve,
    _setup,
)

pytestmark = pytest.mark.anyio

GREETING = "Greet the customer by name when they give it."


def _finding(verdict: str, text: str, edit: str, quotes: list[str], run_id: str) -> dict:
    return {
        "verdict": verdict,
        "text": text,
        "edit": edit,
        "evidence": [{"run_id": run_id, "quote": quote} for quote in quotes],
    }


async def test_a_finding_names_its_line_and_a_supported_one_needs_a_quote(db):
    ctx, agent, run = await _setup(db)
    run_id = str(run.id)
    agent.draft_spec = {
        **agent.draft_spec,
        "instructions": f"You answer refund questions.\n{GREETING}",
    }
    await db.flush()
    model = Improver(
        db,
        verify={
            "findings": [
                # A real quote that has nothing to do with greeting: kept, and tied to
                # the line it claims to back, so the reader sees the mismatch.
                _finding("supports", "Greeting helps", GREETING, [COMMENT], run_id),
                _finding("supports", "Customers like names", "Not in the edit", [], run_id),
                _finding("supports", "Names matter", GREETING, ["Never said"], run_id),
                _finding("risk", "It may answer in Klingon", "Answer in Klingon.", [], run_id),
                _finding("removed", "Brevity is gone", "-Be brief.", [], run_id),
                _finding("risk", "It may greet strangers", f"+{GREETING}", [], run_id),
                _finding("removed", "The greeting went", GREETING, [], run_id),
            ],
            "instructions": [],
        },
    )

    request = await _improve(db, ctx, agent, model, kind="verify")

    assert request.status == "completed", request.error
    report = request.report
    assert report is not None
    assert [
        (finding["verdict"], finding["text"], finding["edit"], finding.get("edit_refused"))
        for finding in report["findings"]
    ] == [
        ("supports", "Greeting helps", GREETING, None),
        ("risk", "It may answer in Klingon", "", "edit_not_in_diff"),
        ("removed", "Brevity is gone", "Be brief.", None),
        # Copied with the marker the diff showed it with.
        ("risk", "It may greet strangers", GREETING, None),
        ("removed", "The greeting went", "", "edit_not_in_diff"),
    ]
    assert report["findings"][0]["evidence"][0]["quote"] == COMMENT
    # Each finding refused once; one shown without its line is not listed as unrecorded.
    assert report["dropped"] == {"unsupported": 2}
    assert [(item["reason"], item["change"]["text"]) for item in report["rejected"]] == [
        ("unsupported", "Customers like names"),
        ("unsupported", "Names matter"),
    ]

    read = await AuthoringService(db).for_agent(ctx, agent.id)
    assert read.verify is not None and read.verify.report == report


async def test_a_finding_may_name_a_line_of_the_tool_or_configuration_edit(db):
    ctx, agent, run = await _setup(db)
    run_id = str(run.id)
    agent.draft_spec = {**agent.draft_spec, "description": "Refunds, briefly"}
    await db.flush()
    model = Improver(
        db,
        verify={
            "findings": [
                _finding("risk", "The description narrowed", "Refunds, briefly", [], run_id),
                _finding("supports", "Nothing named", "", [COMMENT], run_id),
            ],
            "instructions": [],
        },
    )

    request = await _improve(db, ctx, agent, model, kind="verify")

    assert request.report is not None
    assert [finding["edit"] for finding in request.report["findings"]] == ["Refunds, briefly", ""]
    assert "rejected" not in request.report
