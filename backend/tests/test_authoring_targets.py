"""What the authoring assistant may propose a change to, and what it may not.

The assistant is checked by evals, so it must never be able to change what checks
it: an eval suite, a threshold, a dataset, a scorer or judge, an environment - nor
widen what an agent may spend or reach. Every shape it can answer with is pinned
here; a new target is a decision to make in review, not a field to slip in.
"""

from __future__ import annotations

import pytest

from app.agents.capabilities import ToolOverride
from app.db.models.authoring import HunkKind, SpecProposalHunk
from app.schemas.authoring import (
    Finding,
    ImprovementProposal,
    InstructionChange,
    RunFindings,
    SkillImprovement,
    ToolChange,
    VerifyFinding,
    VerifyReport,
)

pytestmark = pytest.mark.security

ANSWERS = {
    ImprovementProposal: {"summary", "expected_effect", "instructions", "tools"},
    VerifyReport: {"findings", "instructions", "tools"},
    InstructionChange: {"old_text", "new_text", "after", "rationale", "evidence"},
    ToolChange: {"capability_id", "tool_id", "name", "description", "rationale", "evidence"},
    SkillImprovement: {
        "summary",
        "expected_effect",
        "description",
        "content",
        "rationale",
        "evidence",
    },
    RunFindings: {"findings"},
    Finding: {"observation", "evidence"},
    VerifyFinding: {"verdict", "text", "evidence"},
}

NEVER_A_TARGET = (
    "suite",
    "threshold",
    "dataset",
    "case",
    "scor",
    "judge",
    "environment",
    "model",
    "budget",
    "capabilit",
    "approval",
    "eval",
)


def test_a_hunk_changes_instructions_or_a_tools_name_and_description_only():
    assert {kind.value for kind in HunkKind} == {"instructions", "tool_override"}
    (check,) = [
        constraint
        for constraint in SpecProposalHunk.__table__.constraints
        if constraint.name == "spec_proposal_hunks_ck_spec_proposal_hunk_kind_check"
    ]
    assert str(check.sqltext) == "kind IN ('instructions', 'tool_override')"
    assert set(ToolOverride.model_fields) == {"name", "description"}


@pytest.mark.parametrize("answer", list(ANSWERS), ids=lambda model: model.__name__)
def test_every_answer_the_assistant_gives_holds_only_its_targets(answer):
    assert set(answer.model_fields) == ANSWERS[answer]


def test_nothing_that_checks_an_agent_or_widens_it_is_a_target():
    fields = {name for model in ANSWERS for name in model.model_fields}
    fields |= {kind.value for kind in HunkKind}
    fields |= set(ToolOverride.model_fields)
    # `capability_id` names the binding a tool change belongs to; it is not a change.
    named = {field for field in fields if field != "capability_id"}
    assert not {field for field in named for word in NEVER_A_TARGET if word in field}
