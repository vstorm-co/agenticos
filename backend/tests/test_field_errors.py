"""The one shape a per-field refusal takes, and what it refuses to carry.

Every refusal that names a field builds it here - the validation handler and the
four services that used to hand pydantic's `exc.errors()` through untouched. The
two properties worth pinning are the ones a call site cannot restate for itself:
what the path looks like, and that nothing but the path and the sentence leaves
the process (#882).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_core import ErrorDetails

from app.core.field_errors import field_problems, request_field_problems


class Chunking(BaseModel):
    """A pair rule that names both fields in `msg` and neither in `loc`."""

    size: int = Field(default=512, ge=64)
    overlap: int = 50

    @model_validator(mode="after")
    def overlap_fits(self) -> Chunking:
        if self.overlap >= self.size:
            raise ValueError(f"overlap ({self.overlap}) must be smaller than size ({self.size})")
        return self


class Document(BaseModel):
    """A model whose pair rule sits one level down, where `loc` is not empty."""

    chunking: Chunking = Field(default_factory=Chunking)


def _raise(payload: dict[str, object]) -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        Chunking.model_validate(payload)
    return caught.value


def _one(location: tuple[int | str, ...]) -> list[ErrorDetails]:
    return [{"type": "x", "loc": location, "msg": "too long", "input": None}]


class TestThePathAFormMarksOn:
    @pytest.mark.parametrize(
        ("location", "expected"),
        [
            (("body", "name"), "name"),
            # The Builder posts the whole spec under one key; the field a person
            # is looking at is the leaf, and the path has to reach it.
            (("body", "spec", "name"), "spec.name"),
            (("query", "limit"), "limit"),
            # An index is the most useful part of the path when a list is
            # rejected - "the third capability", not "a capability".
            (("body", "spec", "capabilities", 2, "id"), "spec.capabilities.2.id"),
        ],
    )
    def test_a_request_drops_where_the_value_came_from_and_joins_the_rest(
        self, location: tuple[int | str, ...], expected: str
    ) -> None:
        """A form can do nothing with "body"; `spec.name` is what it marks on."""
        assert request_field_problems(_one(location)) == [
            {"field": expected, "message": "too long"}
        ]

    def test_a_request_body_that_is_not_an_object_belongs_to_no_field(self) -> None:
        assert request_field_problems(_one(("body",))) == [
            {"field": "request", "message": "too long"}
        ]

    def test_a_document_a_service_validated_itself_keeps_its_first_segment(self) -> None:
        """`loc` has no origin on it, so the first element is already a field,
        reported below the name the caller's form gives the whole document."""
        assert field_problems(_one(("chunk_overlap",)), root="ingestion_config") == [
            {"field": "ingestion_config.chunk_overlap", "message": "too long"}
        ]

    def test_a_service_document_names_exactly_what_the_request_path_names(self) -> None:
        """The same rule, refused at the two entry points it has, addressed the
        same way. `chunk_size` sent as a collection's own settings is a field of
        a JSON body and FastAPI reports `("body", "ingestion_config",
        "chunk_size")`; sent as an upload's override it is a document a service
        parses itself and reports `("chunk_size",)`. A form has one input."""
        by_request = request_field_problems(_one(("body", "ingestion_config", "chunk_size")))

        assert by_request == field_problems(_one(("chunk_size",)), root="ingestion_config")

    @pytest.mark.parametrize("name", ["body", "query", "path", "header", "cookie"])
    def test_a_field_named_like_a_request_origin_is_still_that_field(self, name: str) -> None:
        """The two cases are told apart by which caller it is, never by the
        string. A spec is `extra="forbid"`, so a top-level key called `body`
        reports `loc: ("body",)` - and reading that as FastAPI's marker dropped
        it, blaming the editor for a key somebody has to delete."""
        assert field_problems(_one((name,)), root="yaml") == [
            {"field": f"yaml.{name}", "message": "too long"}
        ]

    def test_a_rule_about_the_whole_object_is_given_the_field_it_arrived_in(self) -> None:
        """The wrinkle in #882: a `model_validator(mode="after")` reports `loc: ()`.

        The sentence names both settings, pydantic attributes it to neither, and
        the form still has to be told which input to put it under - so the
        raiser names the field the whole document came in as.
        """
        problems = field_problems(
            _raise({"size": 512, "overlap": 4096}).errors(), root="ingestion_config"
        )

        assert [problem["field"] for problem in problems] == ["ingestion_config"]
        assert "overlap (4096)" in problems[0]["message"]
        assert "size (512)" in problems[0]["message"]

    def test_a_rule_on_a_nested_model_names_that_model_rather_than_the_root(self) -> None:
        """The fallback is for an empty path, and a nested validator has one.

        Pydantic reports the path *to* the object the rule is about, so
        `chunking` is what the form marks - not the whole document, and not the
        two fields the rule mentions in its sentence.
        """
        with pytest.raises(ValidationError) as caught:
            Document.model_validate({"chunking": {"size": 512, "overlap": 4096}})

        assert field_problems(caught.value.errors(), root="ingestion_config") == [
            {
                "field": "ingestion_config.chunking",
                "message": "Value error, overlap (4096) must be smaller than size (512)",
            }
        ]

    def test_every_error_is_reported_not_only_the_first(self) -> None:
        """Fixing a form costs one round trip rather than one per mistake."""
        problems = field_problems(
            _raise({"size": 1, "overlap": "x"}).errors(), root="ingestion_config"
        )

        assert sorted(problem["field"] for problem in problems) == [
            "ingestion_config.overlap",
            "ingestion_config.size",
        ]


class TestNothingElseLeaves:
    def test_the_rejected_value_does_not_come_back_beside_the_field_it_broke(self) -> None:
        """`exc.errors()` carries `input` by default, and a caller can forget to
        turn it off. Reading `loc` and `msg` only is what makes forgetting safe:
        a form needs to know which field is wrong, not to be sent a copy of what
        it posted (`.claude/rules/exceptions-security.md`)."""
        errors = _raise({"size": 12}).errors()
        assert any("input" in error for error in errors)

        problems = field_problems(errors, root="ingestion_config")

        assert all(set(problem) == {"field", "message"} for problem in problems)
        assert "12" not in repr(problems)

    def test_the_exception_object_a_rule_raised_does_not_come_back(self) -> None:
        """A `value_error` puts the `ValueError` itself in `ctx`, and
        `jsonable_encoder` reaches an object it does not recognise through
        `vars()` - so `details` used to carry an empty `{"error": {}}` where the
        rule's own exception had been."""
        problems = field_problems(
            _raise({"size": 100, "overlap": 100}).errors(), root="ingestion_config"
        )

        assert all("ctx" not in problem for problem in problems)

    def test_an_empty_report_is_an_empty_list_rather_than_an_invented_field(self) -> None:
        assert field_problems([], root="ingestion_config") == []
