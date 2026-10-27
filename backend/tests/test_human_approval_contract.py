"""`human.approval`'s schemas: what an editable proposal adds, and that nothing stored breaks."""

import pytest
from pydantic import ValidationError

from app.schemas.workflow_approval import MAX_PROPOSAL_CHARS
from app.services.virtual_tables.types import MAX_LONG_TEXT
from app.workflows.nodes.human_approval._handler import (
    HumanApprovalConfig,
    HumanApprovalInput,
    HumanApprovalOutput,
)


def test_a_stored_output_from_before_validates() -> None:
    output = HumanApprovalOutput.model_validate(
        {"decision": "approved", "decided_by_user_id": None, "decided_at": None, "note": None}
    )
    assert output.final is None
    assert output.original is None
    assert output.edited is False


def test_a_stored_config_from_before_validates() -> None:
    config = HumanApprovalConfig.model_validate({"title": "Send?"})
    assert config.editable is False
    assert config.proposal_format == "text"
    assert config.proposal_label is None


def test_a_proposal_over_the_limit_is_refused() -> None:
    assert HumanApprovalInput(proposal="x" * MAX_PROPOSAL_CHARS).proposal is not None
    with pytest.raises(ValidationError):
        HumanApprovalInput(proposal="x" * 100_001)


def test_an_unknown_format_is_refused() -> None:
    with pytest.raises(ValidationError):
        HumanApprovalConfig.model_validate({"title": "Send?", "proposal_format": "html"})


def test_a_label_over_80_characters_is_refused() -> None:
    assert HumanApprovalConfig(title="Send?", proposal_label="x" * 80).proposal_label
    with pytest.raises(ValidationError):
        HumanApprovalConfig(title="Send?", proposal_label="x" * 81)


def test_the_proposal_limit_is_the_long_text_limit() -> None:
    assert MAX_PROPOSAL_CHARS == MAX_LONG_TEXT
