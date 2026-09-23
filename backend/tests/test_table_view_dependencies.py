"""`_referenced_column_ids`: every column id a saved view's config names.

Pure function, tested directly - `test_table_views.py` (integration) proves the
`DependencyChecker` it feeds refuses archiving a column a view depends on; this
file proves every shape of `config` that function reads is read correctly.
"""

import uuid

from app.services.virtual_tables.table_views import _referenced_column_ids


def test_visible_columns_are_named():
    column_id = uuid.uuid4()

    assert _referenced_column_ids({"visible_columns": [str(column_id)]}) == {column_id}


def test_group_by_is_named():
    column_id = uuid.uuid4()

    assert _referenced_column_ids({"group_by": str(column_id)}) == {column_id}


def test_a_filters_column_id_is_named():
    column_id = uuid.uuid4()

    found = _referenced_column_ids({"filters": [{"column_id": str(column_id), "op": "eq"}]})

    assert found == {column_id}


def test_a_sort_by_a_column_id_is_named():
    column_id = uuid.uuid4()

    assert _referenced_column_ids({"sort": {"by": str(column_id)}}) == {column_id}


def test_a_sort_by_created_at_or_updated_at_names_no_column():
    assert _referenced_column_ids({"sort": {"by": "created_at"}}) == set()
    assert _referenced_column_ids({"sort": {"by": "updated_at"}}) == set()


def test_an_empty_config_names_nothing():
    assert _referenced_column_ids({}) == set()


def test_malformed_shapes_are_ignored_rather_than_raising():
    """A stored config a view can never actually hold today - defensive, not reachable."""
    assert (
        _referenced_column_ids(
            {
                "visible_columns": "not-a-list",
                "filters": "not-a-list",
                "sort": "not-a-dict",
            }
        )
        == set()
    )
    assert _referenced_column_ids({"filters": [{"op": "eq"}, "not-a-dict"]}) == set()
