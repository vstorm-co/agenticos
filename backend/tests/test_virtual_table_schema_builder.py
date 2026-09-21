"""Reconciling a submitted column list with the columns a table already has."""

import uuid

import pytest

from app.schemas.virtual_table import MAX_COLUMNS, ColumnDef, ColumnInput, OptionDef, OptionInput
from app.services.virtual_tables import dependencies
from app.services.virtual_tables.dependencies import Dependent, find_dependents
from app.services.virtual_tables.exceptions import InvalidSchemaError
from app.services.virtual_tables.schema import build_columns, diff

pytestmark = pytest.mark.anyio


def _existing(label: str = "Name", **rest) -> ColumnDef:
    return ColumnDef(id=uuid.uuid4(), label=label, type="text", **rest)


def test_an_existing_column_is_matched_by_id_so_a_rename_keeps_it():
    old = _existing("Name")

    (renamed,) = build_columns([ColumnInput(id=old.id, label="Full name", type="text")], [old])

    assert renamed.id == old.id and renamed.label == "Full name"


def test_a_column_left_out_is_archived_after_the_submitted_ones():
    keep, drop = _existing("Keep"), _existing("Drop")

    columns = build_columns(
        [ColumnInput(label="New", type="text"), ColumnInput(id=keep.id, label="Keep", type="text")],
        [drop, keep],
    )

    assert [(c.label, c.archived) for c in columns] == [
        ("New", False),
        ("Keep", False),
        ("Drop", True),
    ]


def test_an_option_listed_twice_is_refused():
    option = OptionDef(id=uuid.uuid4(), label="a")
    old = _existing("Pick", options=[option])
    old = ColumnDef(id=old.id, label="Pick", type="single_select", options=[option])
    twice = [OptionInput(id=option.id, label="a"), OptionInput(id=option.id, label="b")]

    with pytest.raises(InvalidSchemaError, match="listed twice"):
        build_columns(
            [ColumnInput(id=old.id, label="Pick", type="single_select", options=twice)], [old]
        )


def test_an_option_can_be_restored_by_resubmitting_it_unarchived():
    option = OptionDef(id=uuid.uuid4(), label="a", archived=True)
    old = ColumnDef(id=uuid.uuid4(), label="Pick", type="single_select", options=[option])

    (restored,) = build_columns(
        [
            ColumnInput(
                id=old.id,
                label="Pick",
                type="single_select",
                options=[OptionInput(id=option.id, label="a")],
            )
        ],
        [old],
    )

    assert restored.options[0].archived is False


def test_the_column_ceiling_counts_archived_columns_too():
    previous = [_existing(f"Old {n}") for n in range(MAX_COLUMNS)]

    with pytest.raises(InvalidSchemaError, match="at most"):
        build_columns([ColumnInput(label="One too many", type="text")], previous)


def test_the_diff_names_archived_and_newly_required_columns_only():
    stays, dropped = _existing("Stays"), _existing("Dropped")
    already_gone = _existing("Gone", archived=True)
    now_required = _existing("Later")

    current = build_columns(
        [
            ColumnInput(id=stays.id, label="Stays", type="text"),
            ColumnInput(id=now_required.id, label="Later", type="text", nullable=False),
            ColumnInput(label="Brand new", type="text", nullable=False, default="x"),
        ],
        [stays, dropped, already_gone, now_required],
    )
    change = diff([stays, dropped, already_gone, now_required], current)

    assert change.archived == {dropped.id}
    assert change.required == {now_required.id}


async def test_registered_checkers_are_all_asked_and_their_answers_joined(monkeypatch):
    monkeypatch.setattr(dependencies, "_checkers", [])
    first, second = uuid.uuid4(), uuid.uuid4()

    async def views(db, *, organization_id, table_id, column_ids):
        return [Dependent(kind="view", id=first)]

    async def flows(db, *, organization_id, table_id, column_ids):
        return [Dependent(kind="workflow", id=second)]

    assert (
        await find_dependents(
            None, organization_id=uuid.uuid4(), table_id=uuid.uuid4(), column_ids=None
        )
        == []
    )
    dependencies.register_dependency_checker(views)
    dependencies.register_dependency_checker(flows)

    found = await find_dependents(
        None, organization_id=uuid.uuid4(), table_id=uuid.uuid4(), column_ids=frozenset()
    )

    assert found == [Dependent("view", first), Dependent("workflow", second)]
