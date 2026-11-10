"""Configuration is dataset-owned and validates before reaching a pipeline."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.dataset import DatasetUpdate
from app.schemas.dataset_helpers import DatasetHelper, DatasetHelperDefaults, DatasetHelpers
from app.schemas.scoring import DatasetScoring


def test_helpers_have_no_user_agent_identity_and_keep_explicit_configuration() -> None:
    model_id = uuid4()
    instructions = "  # Policy\n\nUse the supplied reference.\n"
    helpers = DatasetHelpers(
        generator=DatasetHelper(model_profile_id=model_id, instructions=instructions)
    )
    restored = DatasetHelpers.model_validate_json(helpers.model_dump_json())
    assert restored.generator.model_profile_id == model_id
    assert restored.generator.instructions == instructions.strip()
    assert restored.improver == DatasetHelper()
    assert "agent_id" not in restored.model_dump_json()
    assert DatasetUpdate(helper_settings=helpers).helper_settings == helpers


@pytest.mark.parametrize("instructions", ["", "   \n", "x" * 20_001])
def test_invalid_instructions_never_reach_helpers_or_judging(instructions: str) -> None:
    with pytest.raises(ValidationError):
        DatasetHelper(instructions=instructions)
    with pytest.raises(ValidationError):
        DatasetScoring.model_validate({"judge": {"instructions": instructions}})


def test_the_dataset_keeps_the_grading_model_instead_of_discarding_it() -> None:
    model_id = uuid4()
    scoring = DatasetScoring.model_validate(
        {"judge": {"model_profile_id": model_id, "instructions": "Check the reference."}}
    )
    assert scoring.judge.model_profile_id == model_id
    assert scoring.judge.instructions == "Check the reference."
    assert DatasetScoring.model_validate(scoring.model_dump()).judge == scoring.judge
    defaults = DatasetHelperDefaults(judge="Grade", generator="Generate", improver="Improve")
    assert defaults.model_dump() == {
        "judge": "Grade",
        "generator": "Generate",
        "improver": "Improve",
    }
