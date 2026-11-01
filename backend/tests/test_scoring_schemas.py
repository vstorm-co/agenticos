"""What the check vocabulary and a dataset's scoring configuration refuse.

A rule is refused when it is written rather than when it runs: a pattern that
does not compile, or one long enough to make matching expensive, would otherwise
surface as an error on every score.
"""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.dataset import DatasetCaseCreate, DatasetCaseRead, DatasetCaseUpdate
from app.schemas.scoring import (
    CHECK,
    MAX_PATTERN,
    CaseScoreRead,
    JudgeScorer,
    RubricCriterion,
)


class TestChecks:
    def test_a_pattern_that_does_not_compile_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="Not a valid regular expression"):
            CHECK.validate_python({"type": "regex", "value": "(unclosed"})

    def test_a_pattern_past_the_limit_is_refused(self) -> None:
        with pytest.raises(ValidationError, match=f"at most {MAX_PATTERN} characters"):
            CHECK.validate_python({"type": "regex", "value": "a" * (MAX_PATTERN + 1)})

    def test_a_schema_that_is_not_a_json_schema_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="Not a valid JSON Schema"):
            CHECK.validate_python({"type": "json_schema", "schema": {"type": "lots"}})

    @pytest.mark.security
    @pytest.mark.parametrize(
        "schema",
        [
            {"type": "string", "pattern": "^(a|a)*$"},
            {"type": "object", "patternProperties": {"^x": {"type": "integer"}}},
            {"properties": {"name": {"type": "string", "pattern": "^a"}}},
            {"anyOf": [{"type": "integer"}, {"type": "string", "pattern": "^a"}]},
            {"items": {"$defs": {"x": {"pattern": "a"}}}},
            {"$defs": {"code": {"pattern": "^[A-Z]+$"}}, "$ref": "#/$defs/code"},
        ],
    )
    def test_a_schema_that_runs_a_pattern_is_refused(self, schema) -> None:
        with pytest.raises(ValidationError, match="use a regex check"):
            CHECK.validate_python({"type": "json_schema", "schema": schema})

    @pytest.mark.parametrize(
        "schema",
        [
            {"$ref": "https://example.com/schema.json"},
            {"properties": {"a": {"$dynamicRef": "other.json#node"}}},
        ],
    )
    def test_a_reference_outside_the_schema_is_refused(self, schema) -> None:
        with pytest.raises(ValidationError, match="only point inside the schema"):
            CHECK.validate_python({"type": "json_schema", "schema": schema})

    def test_a_property_named_like_a_keyword_is_not_one(self) -> None:
        schema = {"properties": {"pattern": {"type": "string"}}, "$ref": "#/properties"}

        check = CHECK.validate_python({"type": "json_schema", "schema": schema})

        assert check.model_dump(by_alias=True)["schema"] == schema

    def test_a_negative_ceiling_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            CHECK.validate_python({"type": "max_cost_usd", "value": -1})


class TestCaseChecks:
    def test_a_case_with_a_check_scoring_does_not_know_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            DatasetCaseCreate(input="Refund window?", checks=[{"type": "sentiment"}])

    def test_an_edit_is_held_to_the_same_rules(self) -> None:
        with pytest.raises(ValidationError):
            DatasetCaseUpdate(checks=[{"type": "regex", "value": "("}])

    def test_an_edit_that_leaves_the_checks_alone_is_not_checked(self) -> None:
        assert DatasetCaseUpdate(note="Reworded").checks is None

    def test_a_stored_check_is_read_whatever_scoring_now_refuses(self) -> None:
        stored = DatasetCaseRead(
            id=uuid.uuid4(),
            case_id=uuid.uuid4(),
            input="Refund window?",
            checks=[{"type": "sentiment"}],
            source="manual",
            created_at=datetime.now(UTC),
        )

        assert stored.checks[0].type == "sentiment"


class TestJudgeConfiguration:
    def test_a_pass_mark_above_the_scale_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="above the top of the scale"):
            JudgeScorer(scale_max=3, pass_at=4)

    def test_two_criteria_with_one_name_are_refused(self) -> None:
        twin = RubricCriterion(name="tone", description="Polite")

        with pytest.raises(ValidationError, match="share a name"):
            JudgeScorer(criteria=[twin, twin])


class TestOutcome:
    def _score(self, **overrides) -> CaseScoreRead:
        values = {
            "id": uuid.uuid4(),
            "dataset_id": uuid.uuid4(),
            "case_id": uuid.uuid4(),
            "case_revision_id": uuid.uuid4(),
            "question": "Refund window?",
            "results": [],
            "passed": False,
            "review_state": "none",
            "created_at": datetime.now(UTC),
        }
        return CaseScoreRead(**{**values, **overrides})

    def test_without_a_verdict_the_scorers_decide(self) -> None:
        assert self._score().outcome is False

    def test_a_person_s_verdict_decides_over_the_scorers(self) -> None:
        score = self._score(human_passed=True)

        assert score.outcome is True
        assert score.model_dump()["outcome"] is True
