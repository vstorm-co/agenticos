"""What the authoring rows say about themselves in a log line."""

import uuid

import pytest
from pydantic import ValidationError

from app.db.models.authoring import AuthoringRequest, SpecProposalBatch, SpecProposalHunk
from app.db.models.context_proposal import ContextProposal
from app.schemas.authoring import FieldChange, ProposalCheck


def test_each_row_names_itself_by_id_and_state():
    request = AuthoringRequest(id=uuid.uuid4(), kind="improve", target="agent", status="queued")
    batch = SpecProposalBatch(id=uuid.uuid4(), agent_id=uuid.uuid4(), status="open")
    hunk = SpecProposalHunk(id=uuid.uuid4(), kind="instructions", status="pending")
    change = ContextProposal(context_id=uuid.uuid4(), status="pending")

    assert "improve" in repr(request) and "queued" in repr(request)
    assert str(batch.agent_id) in repr(batch) and "open" in repr(batch)
    assert "instructions" in repr(hunk) and "pending" in repr(hunk)
    assert str(change.context_id) in repr(change) and "pending" in repr(change)


def test_a_check_names_a_dataset_or_a_suite_and_not_both():
    assert ProposalCheck(suite_id=uuid.uuid4()).dataset_id is None
    for fields in ({}, {"dataset_id": uuid.uuid4(), "suite_id": uuid.uuid4()}):
        with pytest.raises(ValidationError, match="not both"):
            ProposalCheck.model_validate(fields)


def _change(path: str, op: str, value: object) -> FieldChange:
    return FieldChange.model_validate(
        {"path": path, "op": op, "value": value, "rationale": "r", "expected_effect": "e"}
    )


@pytest.mark.parametrize("value", [None, {}, {"id": "clock"}])
def test_adding_a_capability_under_its_own_path_adds_it_to_the_list(value: object):
    change = _change("capabilities/clock", "add", value)

    assert (change.path, change.value) == ("capabilities", {"id": "clock"})


def test_a_capability_added_under_its_own_path_keeps_its_configuration():
    change = _change("capabilities/web_search", "add", {"config": {"max_results": 3}})

    assert change.value == {"config": {"max_results": 3}, "id": "web_search"}


@pytest.mark.parametrize(
    ("path", "op", "value"),
    [
        ("capabilities/clock", "add", {"id": "web_search"}),
        ("capabilities/clock/config", "add", {}),
        ("capabilities/clock", "remove", None),
        ("capabilities", "add", {"id": "clock"}),
    ],
)
def test_any_other_change_keeps_the_path_it_named(path: str, op: str, value: object):
    change = _change(path, op, value)

    assert (change.path, change.value) == (path, value)
