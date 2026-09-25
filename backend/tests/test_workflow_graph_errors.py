"""`GraphValidationError`'s own invariant: it always names at least one problem."""

import pytest

from app.workflows.graph.errors import GraphValidationError


def test_it_refuses_to_be_constructed_with_no_problems():
    with pytest.raises(ValueError, match="at least one problem"):
        GraphValidationError([])


def test_it_carries_one_field_entry_per_problem():
    error = GraphValidationError([("nodes.a", "broken"), ("edges.b", "also broken")])
    assert error.status_code == 422
    assert error.code == "GRAPH_INVALID"
    assert error.details == {
        "fields": [
            {"field": "nodes.a", "message": "broken"},
            {"field": "edges.b", "message": "also broken"},
        ]
    }
