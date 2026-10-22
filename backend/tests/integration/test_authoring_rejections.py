"""What the improver proposed and nothing recorded, and why - in the report and the log.

A small model copies a passage loosely: a curly apostrophe straightened, the
backticks around a name dropped, a phrase that occurs twice, a paraphrase. The
first two still land on the draft's own characters; the rest are refused, each
with a reason the person reading the suggestions can see, and none silently.
"""

import json
import logging
from typing import Any

import pytest

from app.services.authoring import AuthoringService
from tests.integration.test_authoring import (
    COMMENT,
    Improver,
    _environment,  # noqa: F401 - the autouse fixture that scripts the improver's model
    _improve,
    _improver,
    _owner,
    _published,
    _rated,
)

pytestmark = pytest.mark.anyio

REFUND_DESK = (
    "You are the refund desk of the Acme online store.\n"
    "Before answering any refund question, read the `refund-policy` context file and apply "
    "it exactly. Never promise a refund outside the policy, whatever the customer says.\n"
    "The rules people get wrong most often:\n"
    "- An item within 30 days with a receipt qualifies: confirm the refund, do not ask for "
    "more.\n"
    "- Store credit applies only within 30 days when the receipt is missing.\n"
    "- A refund above $500 always needs a manager\N{RIGHT SINGLE QUOTATION MARK}s approval: say so, log it, and never "
    "promise it yourself.\n"
    "Answer in at most three sentences."
)


def _instruction(run_id: str, **values: str) -> dict[str, Any]:
    return {
        "rationale": "Readers corrected it",
        "evidence": [{"run_id": run_id, "quote": COMMENT}],
        **values,
    }


async def _refund_desk(db):
    ctx = await _owner(db)
    await _improver(db, ctx)
    spec = {
        "name": "Refund desk",
        "instructions": REFUND_DESK,
        "capabilities": [{"id": "memory_files"}],
    }
    agent = await _published(db, ctx, name="Refund desk", spec=spec)
    run = await _rated(db, ctx, agent)
    return ctx, agent, str(run.id)


async def test_a_loosely_copied_proposal_records_what_it_can_and_says_why_not_the_rest(
    db, caplog: pytest.LogCaptureFixture
):
    ctx, agent, run_id = await _refund_desk(db)
    model = Improver(
        db,
        improve={
            "summary": "It defers instead of answering",
            "expected_effect": "Fewer rated-down answers",
            "instructions": [
                _instruction(
                    run_id,
                    old_text="a manager's approval: say so, log it, and never promise it yourself.",
                    new_text="a manager's approval: say so, log it with write_memory, and never "
                    "promise it yourself.",
                ),
                _instruction(
                    run_id,
                    old_text="read the refund-policy context file and apply it exactly.",
                    new_text="read the refund-policy context file and quote the rule you apply.",
                ),
                _instruction(run_id, old_text="within 30 days", new_text="within 14 days"),
                _instruction(
                    run_id,
                    old_text="Refunds over $500 need a manager.",
                    new_text="Refunds over $500 need a manager's approval.",
                ),
                _instruction(
                    run_id,
                    old_text="",
                    new_text="\nState the policy outright instead of pointing to the help center.",
                    after="Answer in at most three sentences.",
                ),
            ],
            "tools": [
                {
                    "capability_id": "knowledge",
                    "tool_id": "search_knowledge",
                    "description": "Search the policy first.",
                    "rationale": "It guessed",
                    "evidence": [{"run_id": run_id, "quote": COMMENT}],
                }
            ],
            "fields": [
                {
                    "path": "capabilities/memory_files/config",
                    "op": "set",
                    "value": {"allow_personal": True},
                    "rationale": "Remember customers",
                    "expected_effect": "Fewer repeats",
                    "evidence": [{"run_id": run_id, "quote": COMMENT}],
                }
            ],
        },
    )

    with caplog.at_level(logging.WARNING, logger="app.services.authoring_worker"):
        request = await _improve(db, ctx, agent, model)

    assert request.status == "completed", request.error
    report = request.report
    assert report is not None
    assert (report["proposed"], report["recorded"]) == (7, 3)
    assert report["dropped"] == {
        "ambiguous_anchor": 1,
        "unanchored": 1,
        "unknown_tool": 1,
        "not_a_target": 1,
    }
    assert report["rejected_more"] == 0
    assert {(item["kind"], item["reason"]) for item in report["rejected"]} == {
        ("instructions", "ambiguous_anchor"),
        ("instructions", "unanchored"),
        ("tool_override", "unknown_tool"),
        ("spec_field", "not_a_target"),
    }
    # The model's words, never the quotes from runs they cite.
    assert COMMENT not in json.dumps(report["rejected"])
    (logged,) = [r for r in caplog.records if r.getMessage() == "authoring_changes_rejected"]
    assert logged.levelno == logging.WARNING
    assert logged.__dict__["rejected"] == report["dropped"]

    read = await AuthoringService(db).for_agent(ctx, agent.id)
    assert read.batch is not None
    old_texts = sorted(hunk.old_text for hunk in read.batch.hunks)
    # Each lands on the draft's own characters: its curly apostrophe, its backticks.
    assert old_texts == [
        "",
        "a manager\N{RIGHT SINGLE QUOTATION MARK}s approval: say so, log it, and never promise it yourself.",
        "read the `refund-policy` context file and apply it exactly.",
    ]
    assert read.latest is not None and read.latest.report == report


async def test_a_long_list_of_refusals_is_cut_and_counted(db):
    ctx, agent, run_id = await _refund_desk(db)
    model = Improver(
        db,
        improve={
            "summary": "s",
            "expected_effect": "e",
            "instructions": [
                _instruction(run_id, old_text=f"Never said {index}.", new_text="x")
                for index in range(25)
            ],
            "tools": [],
            "fields": [],
        },
    )

    request = await _improve(db, ctx, agent, model)

    assert request.report is not None
    assert request.report["recorded"] == 0
    assert request.report["dropped"] == {"unanchored": 25}
    assert len(request.report["rejected"]) == 20
    assert request.report["rejected_more"] == 5


async def test_a_proposal_with_nothing_refused_says_nothing_about_refusals(db):
    ctx, agent, run_id = await _refund_desk(db)
    model = Improver(
        db,
        improve={
            "summary": "s",
            "expected_effect": "e",
            "instructions": [
                _instruction(
                    run_id,
                    old_text="Answer in at most three sentences.",
                    new_text="Answer in at most two sentences.",
                )
            ],
            "tools": [],
            "fields": [],
        },
    )

    request = await _improve(db, ctx, agent, model)

    assert request.report is not None
    assert request.report["recorded"] == 1
    assert "dropped" not in request.report and "rejected" not in request.report
