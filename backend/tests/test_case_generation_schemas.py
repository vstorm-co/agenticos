"""What a decision on drafted cases refuses before it reaches the service, and how rows print."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.db.models.case_generation import CaseGeneration, CaseProposal
from app.schemas.case_generation import (
    MAX_DECIDED,
    CaseGenerationRequest,
    CaseProposalAccept,
    CaseProposalDismiss,
)


def test_a_decision_names_at_least_one_proposal_and_at_most_a_page() -> None:
    with pytest.raises(ValidationError):
        CaseProposalAccept(items=[])
    with pytest.raises(ValidationError):
        CaseProposalDismiss(ids=[uuid.uuid4() for _ in range(MAX_DECIDED + 1)])
    accepted = CaseProposalAccept(items=[{"id": uuid.uuid4()}])
    assert accepted.items[0].content is None


def test_an_edited_draft_is_held_to_a_case_s_rules() -> None:
    with pytest.raises(ValidationError, match="input"):
        CaseProposalAccept(items=[{"id": uuid.uuid4(), "content": {"input": ""}}])


def test_every_row_says_which_dataset_it_belongs_to() -> None:
    dataset_id = uuid.uuid4()
    generation = CaseGeneration(dataset_id=dataset_id, status="running")
    proposal = CaseProposal(dataset_id=dataset_id, origin="red_team")

    assert repr(generation) == f"<CaseGeneration(dataset={dataset_id}, status=running)>"
    assert repr(proposal) == f"<CaseProposal(dataset={dataset_id}, origin=red_team)>"


def test_a_request_names_each_source_once_in_one_order() -> None:
    agent = uuid.uuid4()
    request = CaseGenerationRequest(
        agent_id=agent, sources=["red_team", "agent", "red_team", "knowledge"]
    )
    assert request.sources == ["agent", "knowledge", "red_team"]
    assert request.count == 20
    with pytest.raises(ValidationError):
        CaseGenerationRequest(agent_id=agent, sources=[])
    with pytest.raises(ValidationError):
        CaseGenerationRequest(agent_id=agent, sources=["web"])


def test_a_request_asks_for_at_least_one_case_per_source() -> None:
    agent = uuid.uuid4()
    assert CaseGenerationRequest(agent_id=agent, sources=["agent", "red_team"], count=2).count == 2
    with pytest.raises(ValidationError) as refused:
        CaseGenerationRequest(agent_id=agent, sources=["agent", "knowledge", "red_team"], count=2)
    assert [error["loc"] for error in refused.value.errors()] == [("count",)]
