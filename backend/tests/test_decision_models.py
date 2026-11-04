"""The models a decision step may ask: a catalog that offers, never forbids."""

from app.services.decision_models import (
    DECISION_MODELS,
    DEFAULT_DECISION_MODEL,
    decision_model_schema,
)


def test_the_default_is_the_first_model_of_the_catalog() -> None:
    assert DECISION_MODELS
    assert DECISION_MODELS[0].id == DEFAULT_DECISION_MODEL


def test_the_schema_suggests_every_model_without_closing_the_field() -> None:
    schema = decision_model_schema()

    assert schema["x-suggestions"] == [model.id for model in DECISION_MODELS]
    assert schema["x-enum-labels"] == {model.id: model.name for model in DECISION_MODELS}
    assert "enum" not in schema
