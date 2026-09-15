"""The category/tag label rules, unit-level.

Folding, deduplication and the strict-vs-tolerant split are pure value shaping,
so they are asserted here rather than through a route. The write path raises past
the stored width (a clean 422); the filter path drops and caps rather than
raising, so a bad discovery query narrows the page instead of breaking it.
"""

import unicodedata

import pytest
from pydantic import ValidationError

from app.schemas.agent import (
    LABEL_MAX_LENGTH,
    MAX_CATEGORIES,
    MAX_TAGS,
    AgentMetadataRequest,
    AgentRead,
    _fold_labels,
    normalize_labels_query,
    normalize_labels_strict,
)

pytestmark = pytest.mark.anyio


def test_fold_trims_collapses_whitespace_and_drops_empties():
    assert _fold_labels(["  Sales  ", "  ", "a\t\n b   c "]) == ["sales", "a b c"]


def test_fold_case_folds_where_lower_would_not():
    """`casefold` folds the German sharp s; `lower` leaves it distinct."""
    assert _fold_labels(["Straße"]) == ["strasse"]
    assert _fold_labels(["STRASSE", "straße"]) == ["strasse"]


def test_fold_unifies_composed_and_decomposed_spellings():
    composed = unicodedata.normalize("NFC", "café")
    decomposed = unicodedata.normalize("NFD", "café")
    assert composed != decomposed
    assert _fold_labels([composed, decomposed]) == ["café"]


def test_fold_dedupes_preserving_first_seen_order():
    assert _fold_labels(["b", "A", "a", "B", "c"]) == ["b", "a", "c"]


def test_fold_is_idempotent():
    once = _fold_labels(["Sales", "  Ops ", "sales"])
    assert _fold_labels(once) == once


def test_strict_raises_on_a_value_too_long_after_folding():
    """The check is on the stored, folded value, so a casefold expansion counts."""
    # 17 sharp-s fold to 34 chars ("ss" each), past the 32 column width even
    # though the input is only 17 characters.
    expanding = "ß" * 17
    assert len(expanding) <= LABEL_MAX_LENGTH
    assert len(expanding.casefold()) > LABEL_MAX_LENGTH
    with pytest.raises(ValueError):
        normalize_labels_strict([expanding])


def test_strict_accepts_a_value_at_the_limit():
    assert normalize_labels_strict(["x" * LABEL_MAX_LENGTH]) == ["x" * LABEL_MAX_LENGTH]


def test_query_drops_an_over_length_item_without_raising_or_truncating():
    kept = normalize_labels_query(["ok", "x" * 40], max_items=MAX_TAGS)
    assert kept == ["ok"]


def test_query_caps_to_the_facet_bound():
    many = [f"t{i}" for i in range(50)]
    assert len(normalize_labels_query(many, max_items=MAX_CATEGORIES)) == MAX_CATEGORIES
    assert len(normalize_labels_query(many, max_items=MAX_TAGS)) == MAX_TAGS


def test_query_of_blank_values_is_empty():
    assert normalize_labels_query(["   ", "\t"], max_items=MAX_TAGS) == []


def test_metadata_request_normalizes_duplicates_and_empties():
    body = AgentMetadataRequest(categories=["Sales", "sales", "  "], tags=["X", "x"])
    assert body.categories == ["sales"]
    assert body.tags == ["x"]


def test_metadata_request_rejects_too_many_categories():
    with pytest.raises(ValidationError):
        AgentMetadataRequest(categories=[f"c{i}" for i in range(MAX_CATEGORIES + 1)])


def test_metadata_request_rejects_too_many_tags():
    with pytest.raises(ValidationError):
        AgentMetadataRequest(tags=[f"t{i}" for i in range(MAX_TAGS + 1)])


def test_metadata_request_rejects_an_over_length_item():
    with pytest.raises(ValidationError):
        AgentMetadataRequest(tags=["x" * (LABEL_MAX_LENGTH + 1)])


def test_metadata_request_defaults_to_empty_facets():
    body = AgentMetadataRequest()
    assert body.categories == []
    assert body.tags == []


def test_agent_read_requires_categories_and_tags():
    """A hand-built row that forgets them fails loud rather than reading []."""
    fields = {
        "id": "00000000-0000-0000-0000-000000000001",
        "slug": "support",
        "name": "Support",
        "status": "draft",
        "visibility": "private",
    }
    with pytest.raises(ValidationError):
        AgentRead(**fields)
    ok = AgentRead(**fields, categories=["sales"], tags=["eu"])
    assert ok.categories == ["sales"]
    assert ok.tags == ["eu"]
