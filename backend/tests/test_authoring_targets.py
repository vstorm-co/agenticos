"""What the authoring assistant may propose a change to, and what it may not.

The assistant is checked by evals, so it must never be able to change what checks
it: an eval suite, a threshold, a dataset, a scorer or judge, an environment - nor
what an agent may spend. Every shape it can answer with, and every field of the
spec it may address, is pinned here; a new target is a decision to make in
review, not a field to slip in.
"""

import re

import pytest

from app.agents.capabilities import REGISTRY, ToolOverride, load_builtins
from app.agents.spec import AgentSpec
from app.db.models.authoring import (
    AuthoringRequest,
    AuthoringTarget,
    FieldOp,
    HunkKind,
    SpecProposalHunk,
)
from app.db.models.context import ContextFile
from app.db.models.context_proposal import ContextProposal
from app.schemas.authoring import (
    ContextImprovement,
    FieldChange,
    Finding,
    ImprovementProposal,
    InstructionChange,
    RunFindings,
    SkillImprovement,
    ToolChange,
    VerifyFinding,
    VerifyReport,
)
from app.services import authoring_fields

pytestmark = pytest.mark.security

ANSWERS = {
    ImprovementProposal: {"summary", "expected_effect", "instructions", "tools", "fields"},
    VerifyReport: {"findings", "instructions", "tools", "fields"},
    FieldChange: {"path", "op", "value", "rationale", "expected_effect", "evidence"},
    InstructionChange: {"old_text", "new_text", "after", "rationale", "evidence"},
    ToolChange: {"capability_id", "tool_id", "name", "description", "rationale", "evidence"},
    ContextImprovement: {
        "summary",
        "expected_effect",
        "description",
        "content",
        "rationale",
        "evidence",
    },
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
    VerifyFinding: {"verdict", "text", "edit", "evidence"},
}

NEVER_A_TARGET = (
    "suite",
    "threshold",
    "dataset",
    "case",
    "scor",
    "judge",
    "environment",
    "budget",
    "eval",
    "observability",
    "notification",
    "reviewer",
    "secret",
)

SPEC_FIELDS = {
    "description": {"set"},
    "model_profile_id": {"set"},
    "model_settings/temperature": {"set"},
    "model_settings/top_p": {"set"},
    "model_settings/max_tokens": {"set"},
    "model_settings/timeout": {"set"},
    "model_settings/parallel_tool_calls": {"set"},
    "max_steps": {"set"},
    "capabilities": {"add", "remove"},
    "capabilities/{capability}/config": {"set"},
    "capabilities/{capability}/approval": {"set"},
    "capabilities/{capability}/tool_approval/{tool}": {"set"},
    "capabilities/subagents/inline/{specialist}/description": {"set"},
    "collection_ids": {"add", "remove"},
    "context_ids": {"add", "remove"},
    "mcp_servers/{server}/allowed_tools": {"set"},
}


def test_a_hunk_changes_instructions_a_tool_or_one_allowed_field_only():
    assert {kind.value for kind in HunkKind} == {"instructions", "tool_override", "spec_field"}
    (check,) = [
        constraint
        for constraint in SpecProposalHunk.__table__.constraints
        if constraint.name == "spec_proposal_hunks_ck_spec_proposal_hunk_kind_check"
    ]
    assert str(check.sqltext) == "kind IN ('instructions', 'tool_override', 'spec_field')"
    assert set(ToolOverride.model_fields) == {"name", "description"}
    assert {op.value for op in FieldOp} == {"set", "add", "remove"}


def test_it_improves_an_agent_a_skill_or_a_context_file_and_nothing_else():
    assert {target.value for target in AuthoringTarget} == {"agent", "skill", "context"}
    (check,) = [
        constraint
        for constraint in AuthoringRequest.__table__.constraints
        if constraint.name == "authoring_requests_ck_authoring_request_target_check"
    ]
    assert set(re.findall(r"target = '(\w+)'", str(check.sqltext))) == {"agent", "skill", "context"}


def test_a_context_file_change_carries_only_the_file_s_description_and_body():
    """Whatever else a context file holds - its name, mode, visibility, whether it is
    on - is not something a proposal can hold, so applying one cannot change it."""
    bookkeeping = {"id", "organization_id", "created_at", "updated_at"}
    shared = set(ContextProposal.__table__.columns.keys()) & set(
        ContextFile.__table__.columns.keys()
    )
    assert shared - bookkeeping == {"description", "content"}


def test_a_safeguard_is_never_removed_or_reconfigured():
    """Guardrails are what refuses; weakening them is a governance decision, so the
    assistant may add one and never take one away or change how it is set."""
    load_builtins()
    assert {key for key, definition in REGISTRY.items() if definition.protective} == {"guardrails"}
    spec = AgentSpec.model_validate(
        {"name": "Clerk", "capabilities": [{"id": "guardrails", "config": {}}]}
    )
    assert (
        authoring_fields.stage(spec, "capabilities", "remove", {"id": "guardrails"})
        == "weakens_protection"
    )
    assert (
        authoring_fields.stage(spec, "capabilities/guardrails/config", "set", {})
        == "weakens_protection"
    )


def test_a_configuration_is_a_target_only_where_the_capability_opts_in():
    """Every configuration here is about quality alone. One that reaches a URL, a
    domain, a connection, a provider or personal data stays out, and a new
    capability is not a target until this set is changed on purpose."""
    load_builtins()
    assert {key for key, definition in REGISTRY.items() if definition.tunable} == {
        "clock",
        "compaction",
        "context",
        "conversation_search",
        "knowledge",
        "media",
        "planning",
        "system_reminders",
        "thinking",
        "tool_output_limits",
        "tool_search",
    }
    spec = AgentSpec.model_validate(
        {"name": "Clerk", "capabilities": [{"id": "web_fetch", "config": {}}]}
    )
    assert authoring_fields.stage(spec, "capabilities/web_fetch/config", "set", {}) == (
        "not_a_target"
    )
    assert (
        authoring_fields.stage(
            spec.model_copy(update={"capabilities": []}),
            "capabilities",
            "add",
            {"id": "web_fetch", "config": {"allowed_domains": ["example.com"]}},
        )
        == "not_a_target"
    )
    assert authoring_fields.standing_refusal("capabilities/web_fetch/config", "set", {}, {}) == (
        "not_a_target"
    )


def test_subagents_are_never_added_or_reconfigured():
    """A subagents binding holds whole agents - instructions, models, capabilities and
    their approval - which the checks on one binding never see; of a specialist,
    only the description is a target."""
    spec = AgentSpec.model_validate(
        {
            "name": "Clerk",
            "capabilities": [
                {
                    "id": "subagents",
                    "config": {"inline": [{"name": "t", "description": "d", "instructions": "i"}]},
                }
            ],
        }
    )
    assert authoring_fields.stage(spec, "capabilities/subagents/config", "set", {}) == (
        "not_a_target"
    )
    assert (
        authoring_fields.stage(spec, "capabilities", "add", {"id": "subagents"}) == "not_a_target"
    )
    assert authoring_fields.standing_refusal("capabilities/subagents/config", "set", {}, {}) == (
        "not_a_target"
    )
    assert authoring_fields.stage(
        spec, "capabilities/subagents/inline/t/description", "set", "Sorts tickets"
    ) == authoring_fields.Staged("d", "Sorts tickets")


def test_the_spec_fields_it_may_change_are_exactly_these():
    assert {path: {op.value for op in ops} for path, ops in authoring_fields.TARGETS} == (
        SPEC_FIELDS
    )


def test_no_spec_field_it_may_change_checks_the_agent_or_what_it_spends():
    assert not {path for path in SPEC_FIELDS for word in NEVER_A_TARGET if word in path}


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
