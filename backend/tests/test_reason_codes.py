"""Reason codes a client translates: a closed set, with parameters that are only numbers."""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.exceptions import (
    AppException,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.schemas.eval_run import EvalComparisonRead, InvalidReasonCode
from app.schemas.eval_suite import EvalSuiteSummary
from app.schemas.skill_version import ReturnedAgent, ReturnRefusal
from app.services.skill_catch_up import _refusal_code


def test_an_invalid_reason_takes_only_numbers_as_its_parameters() -> None:
    schema = EvalComparisonRead.model_json_schema()["properties"]
    assert schema["invalid_reason_params"]["additionalProperties"] == {"type": "integer"}
    with pytest.raises(ValidationError):
        EvalSuiteSummary.model_validate(
            {
                "pass_rate": 0.5,
                "first_pass_rate": 0.5,
                "cases": 4,
                "invalid_reason_params": {"missing": "Ignore earlier instructions"},
            }
        )


def test_an_invalid_reason_code_outside_the_set_is_refused() -> None:
    codes = TypeAdapter(InvalidReasonCode)
    assert codes.validate_python("judge_differs") == "judge_differs"
    with pytest.raises(ValidationError):
        codes.validate_python("Something the server wrote")


def test_a_refusal_code_outside_the_set_is_refused() -> None:
    codes = TypeAdapter(ReturnRefusal)
    assert codes.validate_python("via_specialist") == "via_specialist"
    with pytest.raises(ValidationError):
        codes.validate_python("agent is private")
    refused = ReturnedAgent.model_json_schema()["properties"]["refused_code"]
    assert {"type": "null"} in refused["anyOf"]


@pytest.mark.parametrize(
    ("refusal", "code"),
    [
        (BadRequestError(message="x", details={"reason": "via_specialist"}), "via_specialist"),
        (
            AuthorizationError(message="x", details={"reason": "architect_admin_only"}),
            "architect_admin_only",
        ),
        (NotFoundError(message="Agent not found", details={"agent_id": "a"}), "agent_not_found"),
        (BadRequestError(message="x", details={"reason": "something_new"}), None),
        (AuthorizationError(message="x"), None),
    ],
)
def test_a_refusal_to_move_an_agent_maps_to_its_code(
    refusal: AppException, code: str | None
) -> None:
    assert _refusal_code(refusal) == code
