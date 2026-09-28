"""Reconciling a submitted column list with the columns a table already has."""

import uuid

import pytest

from app.schemas.virtual_table import (
    MAX_COLUMNS,
    MAX_OPTIONS,
    ColumnDef,
    ColumnInput,
    OptionDef,
    OptionInput,
)
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


def _built(**column) -> ColumnDef:
    (built,) = build_columns([ColumnInput(label="C", **column)], [])
    return built


def test_a_whole_number_default_is_stored_as_an_integer():
    """3.0 would otherwise sit in every record as JSONB 3.0 and break the bigint cast."""
    default = _built(type="integer", default=3.0).default

    assert default == 3 and isinstance(default, int)


def test_a_datetime_default_is_stored_in_utc():
    default = _built(type="datetime", default="2026-01-05T10:00:00+02:00").default

    assert default == "2026-01-05T08:00:00.000000+00:00"


def test_a_select_default_is_stored_as_the_canonical_option_id():
    option = uuid.uuid4()
    old = ColumnDef(
        id=uuid.uuid4(),
        label="Pick",
        type="single_select",
        options=[OptionDef(id=option, label="a")],
    )

    (rebuilt,) = build_columns(
        [
            ColumnInput(
                id=old.id,
                label="Pick",
                type="single_select",
                options=[OptionInput(id=option, label="a")],
                default=str(option).upper(),
            )
        ],
        [old],
    )

    assert rebuilt.default == str(option)


def _required(**rest) -> ColumnDef:
    return ColumnDef(id=uuid.uuid4(), label="Name", type="text", nullable=False, **rest)


def test_a_required_column_coming_back_from_the_archive_without_a_default_is_flagged():
    archived = _required(archived=True)
    restored = build_columns(
        [ColumnInput(id=archived.id, label="Name", type="text", nullable=False)], [archived]
    )

    assert diff([archived], restored).required == {archived.id}


def test_a_required_column_coming_back_with_a_default_is_not_flagged():
    archived = _required(archived=True, default="x")
    restored = build_columns(
        [ColumnInput(id=archived.id, label="Name", type="text", nullable=False, default="x")],
        [archived],
    )

    assert diff([archived], restored).required == frozenset()


def test_a_required_column_that_stays_archived_or_stays_live_is_not_flagged():
    live = _required()
    archived = _required(archived=True)

    stays_live = build_columns(
        [ColumnInput(id=live.id, label="Name", type="text", nullable=False)], [live]
    )
    stays_archived = build_columns([], [archived])

    assert diff([live], stays_live).required == frozenset()
    assert diff([archived], stays_archived).required == frozenset()


def _select(options: list[OptionDef]) -> ColumnDef:
    return ColumnDef(id=uuid.uuid4(), label="Pick", type="single_select", options=options)


def _labelled(prefix: str, count: int) -> list[OptionDef]:
    return [OptionDef(id=uuid.uuid4(), label=f"{prefix}{n}") for n in range(count)]


def _submit(column: ColumnDef, options: list[OptionInput]) -> list[ColumnInput]:
    return [ColumnInput(id=column.id, label="Pick", type="single_select", options=options)]


def test_a_column_may_hold_exactly_the_option_limit_archived_ones_included():
    live = _labelled("a", 60)
    archived = [OptionDef(id=uuid.uuid4(), label=f"old{n}", archived=True) for n in range(40)]
    column = _select([*live, *archived])

    (rebuilt,) = build_columns(
        _submit(column, [OptionInput(id=o.id, label=o.label) for o in live]), [column]
    )

    assert len(rebuilt.options) == MAX_OPTIONS
    assert sum(o.archived for o in rebuilt.options) == 40


def test_replacing_a_full_option_list_is_refused_rather_than_doubling_it():
    column = _select(_labelled("a", MAX_OPTIONS))
    replacement = [OptionInput(label=f"b{n}") for n in range(MAX_OPTIONS)]

    with pytest.raises(InvalidSchemaError, match="archived ones included") as raised:
        build_columns(_submit(column, replacement), [column])

    assert raised.value.details["fields"][0]["field"] == "columns.0.options"


def test_the_growth_stops_at_the_limit_however_many_times_it_is_tried():
    column = _select(_labelled("a", 50))
    previous = [column]
    for round_ in range(4):
        submitted = [OptionInput(label=f"r{round_}x{n}") for n in range(50)]
        try:
            (column,) = build_columns(_submit(column, submitted), previous)
        except InvalidSchemaError:
            break
        previous = [column]

    assert len(previous[0].options) <= MAX_OPTIONS
    assert round_ >= 1


def test_a_read_column_can_be_sent_back_as_a_change_at_the_limit():
    """A `TableRead` must round-trip through `SchemaUpdate`, which caps each option list."""
    column = _select(_labelled("a", MAX_OPTIONS))
    as_read = ColumnDef.model_validate(column.model_dump(mode="json"))

    resubmitted = ColumnInput.model_validate(
        {
            **as_read.model_dump(mode="json"),
            "options": [o.model_dump(mode="json") for o in as_read.options],
        }
    )

    (rebuilt,) = build_columns([resubmitted], [column])
    assert rebuilt == column
