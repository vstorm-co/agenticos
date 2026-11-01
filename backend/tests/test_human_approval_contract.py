"""`human.approval`'s schemas: what an editable proposal adds, and that nothing stored breaks."""

import pytest
from pydantic import ValidationError

from app.schemas.workflow_approval import MAX_PROPOSAL_CHARS
from app.services.virtual_tables.types import MAX_LONG_TEXT
from app.workflows._registry import REGISTRY
from app.workflows.nodes.human_approval._handler import (
    ApprovalChoice,
    HumanApprovalConfig,
    HumanApprovalInput,
    HumanApprovalOutput,
    ports_for,
    routes,
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


def _with_choices(*ids: str) -> HumanApprovalConfig:
    return HumanApprovalConfig(
        title="Send?", choices=tuple(ApprovalChoice(id=name, label=name.title()) for name in ids)
    )


def test_a_stored_config_and_output_from_before_choices_validate() -> None:
    assert HumanApprovalConfig.model_validate({"title": "Send?"}).choices == ()
    output = HumanApprovalOutput.model_validate({"decision": "approved"})
    assert output.choice is None


@pytest.mark.parametrize("name", ["draft", "send_now", "a", "a1_b2", "x" * 32])
def test_a_choice_id_in_the_pattern_is_accepted(name: str) -> None:
    assert ApprovalChoice(id=name, label="Label").id == name


@pytest.mark.parametrize(
    "name", ["", "Draft", "1draft", "_draft", "dra-ft", "x" * 33, "in", "rejected", "approved"]
)
def test_a_choice_id_outside_the_pattern_or_reserved_is_refused(name: str) -> None:
    with pytest.raises(ValidationError):
        ApprovalChoice(id=name, label="Label")


@pytest.mark.parametrize("label", ["", "x" * 41])
def test_a_choice_label_of_the_wrong_length_is_refused(label: str) -> None:
    with pytest.raises(ValidationError):
        ApprovalChoice(id="draft", label=label)


def test_a_choice_label_of_40_characters_is_accepted() -> None:
    assert ApprovalChoice(id="draft", label="x" * 40).label == "x" * 40


def test_a_choice_takes_no_unknown_field() -> None:
    with pytest.raises(ValidationError):
        ApprovalChoice.model_validate({"id": "draft", "label": "Draft", "colour": "red"})


def test_five_choices_are_accepted_and_six_refused() -> None:
    assert len(_with_choices("a", "b", "c", "d", "e").choices) == 5
    with pytest.raises(ValidationError):
        _with_choices("a", "b", "c", "d", "e", "f")


def test_two_choices_with_one_id_are_refused() -> None:
    with pytest.raises(ValidationError, match="an id of its own"):
        _with_choices("draft", "draft")


def test_without_choices_the_ports_are_the_static_ones() -> None:
    static = [port.id for port in REGISTRY["human.approval"][1].ports]
    assert static == ["in", "approved", "rejected"]
    assert [port.id for port in ports_for(HumanApprovalConfig(title="Send?"))] == static
    assert [port.id for port in ports_for(None)] == static


def test_with_choices_the_ports_are_in_each_choice_then_rejected() -> None:
    ports = ports_for(_with_choices("draft", "send_now"))
    assert [(port.id, port.label, port.kind) for port in ports] == [
        ("in", "In", "input"),
        ("draft", "Draft", "output"),
        ("send_now", "Send_Now", "output"),
        ("rejected", "Rejected", "output"),
    ]
    assert all(port.schema is HumanApprovalOutput for port in ports[1:])


def test_the_definition_keeps_exclusive_branches_and_registers_its_ports() -> None:
    definition = REGISTRY["human.approval"][1]
    assert definition.exclusive_branches is True
    assert definition.ports_for is ports_for


def test_an_approval_with_a_choice_leaves_by_it() -> None:
    assert routes({"decision": "approved", "choice": "draft"}) == frozenset({"draft"})


def test_an_approval_without_a_choice_leaves_by_approved() -> None:
    assert routes({"decision": "approved", "choice": None}) == frozenset({"approved"})
    assert routes({"decision": "approved"}) == frozenset({"approved"})


def test_a_rejection_and_an_expiry_leave_by_rejected_whatever_the_choice() -> None:
    assert routes({"decision": "rejected", "choice": "draft"}) == frozenset({"rejected"})
    assert routes({"decision": "expired"}) == frozenset({"rejected"})
