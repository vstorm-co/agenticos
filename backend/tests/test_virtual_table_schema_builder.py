"""Reconciling a submitted column list with the columns a table already has."""

import uuid

import pytest

from app.core.permissions import AuthContext
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

    async def views(db, *, organization_id, table_id, column_ids, caller):
        return [Dependent(kind="view", id=first, name="Mine")]

    async def flows(db, *, organization_id, table_id, column_ids, caller):
        return [Dependent(kind="workflow", id=second, name="Sync")]

    assert (
        await find_dependents(
            None,
            organization_id=uuid.uuid4(),
            table_id=uuid.uuid4(),
            column_ids=None,
            caller=AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner"),
        )
        == []
    )
    dependencies.register_dependency_checker(views)
    dependencies.register_dependency_checker(flows)

    found = await find_dependents(
        None,
        organization_id=uuid.uuid4(),
        table_id=uuid.uuid4(),
        column_ids=frozenset(),
        caller=AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner"),
    )

    assert found == [Dependent("view", first, "Mine"), Dependent("workflow", second, "Sync")]


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


class TestWhatAReferenceNames:
    """The rules a link, lookup or rollup column's references follow before any is looked up."""

    TABLE = uuid.uuid4()
    LINK = uuid.uuid4()
    TARGET = uuid.uuid4()

    def _link(self) -> ColumnDef:
        return ColumnDef(id=self.LINK, label="Items", type="link", link_table_id=self.TABLE)

    def _build(self, *submitted: ColumnInput) -> list[ColumnDef]:
        link = self._link()
        return build_columns(
            [
                ColumnInput(id=link.id, label="Items", type="link", link_table_id=self.TABLE),
                *submitted,
            ],
            [link],
        )

    def test_a_lookup_and_each_rollup_build_when_they_name_what_they_read(self):
        built = self._build(
            ColumnInput(
                label="Names", type="lookup", link_column_id=self.LINK, target_column_id=self.TARGET
            ),
            ColumnInput(label="Count", type="rollup", link_column_id=self.LINK, aggregate="count"),
            ColumnInput(
                label="Sum",
                type="rollup",
                link_column_id=self.LINK,
                target_column_id=self.TARGET,
                aggregate="sum",
            ),
        )

        assert [column.type for column in built] == ["link", "lookup", "rollup", "rollup"]
        assert built[3].aggregate == "sum" and built[3].target_column_id == self.TARGET

    @pytest.mark.parametrize(
        ("submitted", "field"),
        [
            ({"type": "text", "link_table_id": TABLE}, "link_table_id"),
            ({"type": "link"}, "link_table_id"),
            ({"type": "link", "link_table_id": TABLE, "default": [str(TABLE)]}, "default"),
            ({"type": "text", "link_column_id": LINK}, "link_column_id"),
            ({"type": "lookup", "target_column_id": TARGET}, "link_column_id"),
            (
                {
                    "type": "lookup",
                    "link_column_id": LINK,
                    "target_column_id": TARGET,
                    "aggregate": "sum",
                },
                "aggregate",
            ),
            ({"type": "rollup", "link_column_id": LINK, "target_column_id": TARGET}, "aggregate"),
            ({"type": "lookup", "link_column_id": LINK}, "target_column_id"),
            (
                {
                    "type": "rollup",
                    "link_column_id": LINK,
                    "aggregate": "count",
                    "target_column_id": TARGET,
                },
                "target_column_id",
            ),
            (
                {
                    "type": "lookup",
                    "link_column_id": LINK,
                    "target_column_id": TARGET,
                    "nullable": False,
                },
                "nullable",
            ),
        ],
    )
    def test_a_reference_named_where_it_does_not_belong_or_missing_is_refused(
        self, submitted, field
    ):
        with pytest.raises(InvalidSchemaError) as refused:
            self._build(ColumnInput(label="New", **submitted))

        assert refused.value.details["fields"][0]["field"] == f"columns.1.{field}"

    def test_a_link_cannot_become_another_type_or_another_type_a_link(self):
        link = self._link()
        text = _existing("Ref")

        with pytest.raises(InvalidSchemaError, match="cannot become"):
            build_columns([ColumnInput(id=link.id, label="Items", type="text")], [link])
        with pytest.raises(InvalidSchemaError, match="cannot become"):
            build_columns(
                [ColumnInput(id=text.id, label="Ref", type="link", link_table_id=self.TABLE)],
                [text],
            )


@pytest.mark.parametrize("submitted", [{"type": "formula"}, {"type": "number", "formula": "1 + 1"}])
def test_a_formula_belongs_to_a_formula_column_and_only_there(submitted):
    with pytest.raises(InvalidSchemaError) as refused:
        build_columns([ColumnInput(label="F", **submitted)], [])

    assert refused.value.details["fields"][0]["field"] == "columns.0.formula"


def test_an_archived_formula_is_kept_without_being_checked_again():
    price = _existing("Price")
    total = ColumnDef(id=uuid.uuid4(), label="Total", type="formula", formula="{Price} * 2")

    built = build_columns([ColumnInput(id=price.id, label="Price", type="text")], [price, total])

    assert built[1].archived and built[1].formula == "{Price} * 2"


class TestRevision:
    """A column's `revision` moves when what its values mean changes, and only then."""

    LINKED = uuid.uuid4()

    def _resubmit(self, column: ColumnDef, **change) -> ColumnInput:
        """`column` as a client reads it and sends it back, `revision` included, with `change`."""
        return ColumnInput.model_validate({**column.model_dump(mode="json"), **change})

    def test_a_stored_column_without_one_loads_as_zero(self):
        stored = {"id": str(uuid.uuid4()), "label": "Name", "type": "text"}

        assert ColumnDef.model_validate(stored).revision == 0

    def test_a_new_column_starts_at_zero_whatever_the_client_sends(self):
        (built,) = build_columns(
            [ColumnInput.model_validate({"label": "Name", "type": "text", "revision": 7})], []
        )

        assert built.revision == 0

    def test_a_read_column_sent_back_unchanged_keeps_its_revision_and_changes_nothing(self):
        old = _existing("Name", revision=3)

        built = build_columns([self._resubmit(old, revision=9)], [old])

        assert built == [old]

    @pytest.mark.parametrize(
        "change",
        [{"label": "Full name"}, {"nullable": False, "default": "-"}, {"default": "x"}],
    )
    def test_a_label_default_or_requiredness_leaves_it(self, change):
        old = _existing("Name", revision=2)

        (built,) = build_columns([self._resubmit(old, **change)], [old])

        assert built.revision == 2

    def test_a_type_conversion_bumps_it(self):
        old = _existing("Amount", revision=1)

        (built,) = build_columns([self._resubmit(old, type="long_text")], [old])

        assert built.revision == 2

    def test_archiving_restoring_and_leaving_out_a_column_each_bump_it(self):
        old = _existing("Name")

        (archived,) = build_columns([self._resubmit(old, archived=True)], [old])
        (restored,) = build_columns([self._resubmit(archived, archived=False)], [archived])
        (left_out,) = build_columns([], [restored])
        (still_out,) = build_columns([], [left_out])

        assert [archived.revision, restored.revision, left_out.revision] == [1, 2, 3]
        assert still_out.revision == 3

    def test_what_a_reference_reads_bumps_it(self):
        link = ColumnDef(id=uuid.uuid4(), label="Items", type="link", link_table_id=self.LINKED)
        other = ColumnDef(id=uuid.uuid4(), label="More", type="link", link_table_id=self.LINKED)
        rollup = ColumnDef(
            id=uuid.uuid4(),
            label="Total",
            type="rollup",
            link_column_id=link.id,
            target_column_id=uuid.uuid4(),
            aggregate="sum",
        )
        previous = [link, other, rollup]

        def rebuilt(**change) -> ColumnDef:
            links = [self._resubmit(link), self._resubmit(other)]
            return build_columns([*links, self._resubmit(rollup, **change)], previous)[2]

        assert rebuilt().revision == 0
        assert rebuilt(aggregate="max").revision == 1
        assert rebuilt(target_column_id=str(uuid.uuid4())).revision == 1
        assert rebuilt(link_column_id=str(other.id)).revision == 1
        assert rebuilt(aggregate="count", target_column_id=None).revision == 1

    def test_a_rename_rewrites_formulas_without_bumping_them_and_an_edit_bumps(self):
        price = _existing("Price", revision=4)
        total = ColumnDef(
            id=uuid.uuid4(), label="Total", type="formula", formula="{Price} * 2", revision=1
        )
        previous = [price, total]

        renamed_price, kept = build_columns(
            [self._resubmit(price, label="Cost"), self._resubmit(total)], previous
        )
        _, edited = build_columns(
            [self._resubmit(price), self._resubmit(total, formula="{Price} * 3")], previous
        )

        assert kept.formula == "{Cost} * 2"
        assert (renamed_price.revision, kept.revision) == (4, 1)
        assert edited.revision == 2

    def test_a_formula_sent_with_the_new_label_is_no_edit_either(self):
        price = _existing("Price")
        total = ColumnDef(id=uuid.uuid4(), label="Total", type="formula", formula="{Price} * 2")

        _, kept = build_columns(
            [
                self._resubmit(price, label="Cost"),
                self._resubmit(total, formula="{ Cost } * 2"),
            ],
            [price, total],
        )

        assert kept.revision == 0

    def test_archiving_or_restoring_an_option_bumps_it_and_adding_or_relabelling_one_does_not(
        self,
    ):
        kept, other = OptionDef(id=uuid.uuid4(), label="a"), OptionDef(id=uuid.uuid4(), label="b")
        column = _select([kept, other])

        def rebuilt(*options: OptionInput) -> ColumnDef:
            return build_columns(_submit(column, list(options)), [column])[0]

        both = (OptionInput(id=kept.id, label="a"), OptionInput(id=other.id, label="b"))
        assert rebuilt(*both, OptionInput(label="c")).revision == 0
        assert rebuilt(*both, OptionInput(label="d", archived=True)).revision == 0
        assert rebuilt(OptionInput(id=kept.id, label="A"), both[1]).revision == 0
        assert rebuilt(both[0], OptionInput(id=other.id, label="b", archived=True)).revision == 1
        assert rebuilt(both[0]).revision == 1

        archived = rebuilt(both[0])
        (restored,) = build_columns(
            [self._resubmit(archived, options=[o.model_dump(mode="json") for o in column.options])],
            [archived],
        )
        assert restored.revision == 2

    def _formula(self, formula: str) -> ColumnDef:
        return ColumnDef(id=uuid.uuid4(), label="Total", type="formula", formula=formula)

    def test_swapped_labels_bump_a_formula_only_when_it_reads_other_columns(self):
        price, cost = _existing("Price"), _existing("Cost")
        total = self._formula("{Price} * 2")
        previous = [price, cost, total]
        swapped = [self._resubmit(price, label="Cost"), self._resubmit(cost, label="Price")]

        *_, kept = build_columns([*swapped, self._resubmit(total)], previous)
        # Sent in the labels it was read with, so `{Cost}` is the column then called Cost.
        *_, repointed = build_columns(
            [*swapped, self._resubmit(total, formula="{Cost} * 2")], previous
        )

        assert (kept.formula, kept.revision) == ("{Cost} * 2", 0)
        assert (repointed.formula, repointed.revision) == ("{Price} * 2", 1)

    def test_several_renames_at_once_leave_a_formula_reading_them(self):
        price, count = _existing("Price"), _existing("Count")
        total = self._formula("{Price} * {Count}")

        *_, kept = build_columns(
            [
                self._resubmit(price, label="Unit price"),
                self._resubmit(count, label="Quantity"),
                self._resubmit(total),
            ],
            [price, count, total],
        )

        assert (kept.formula, kept.revision) == ("{Unit price} * {Quantity}", 0)

    def test_a_rename_and_a_formula_edit_in_one_change_bump_it(self):
        price = _existing("Price")
        total = self._formula("{Price} * 2")

        _, edited = build_columns(
            [self._resubmit(price, label="Cost"), self._resubmit(total, formula="{Price} * 3")],
            [price, total],
        )

        assert (edited.formula, edited.revision) == ("{Cost} * 3", 1)

    def test_a_label_taken_over_by_a_new_column_bumps_the_formula_reading_it(self):
        price = _existing("Price")
        total = self._formula("{Price} * 2")

        _, rebuilt, archived = build_columns(
            [ColumnInput(label="Price", type="text"), self._resubmit(total)], [price, total]
        )

        assert archived.id == price.id and archived.archived
        assert (rebuilt.formula, rebuilt.revision) == ("{Price} * 2", 1)

    def test_a_label_taken_over_by_a_renamed_column_bumps_the_formula_reading_it(self):
        price, cost = _existing("Price"), _existing("Cost")
        total = self._formula("{Price} + {Cost}")

        rebuilt, *_ = build_columns(
            [self._resubmit(total), self._resubmit(cost, label="Price")], [price, cost, total]
        )

        assert (rebuilt.formula, rebuilt.revision) == ("{Price} + {Price}", 1)


def test_select_colors_and_label_defaults_are_stored_as_option_ids() -> None:
    columns = build_columns(
        [
            ColumnInput(
                label="Status",
                type="single_select",
                options=[
                    OptionInput(label="Todo", color="blue"),
                    OptionInput(label="Done", color="green"),
                ],
                default="Todo",
            ),
            ColumnInput(
                label="Tags",
                type="multi_select",
                options=[
                    OptionInput(label="API", color="purple"),
                    OptionInput(label="Docs", color="yellow"),
                ],
                default=["API", "Docs"],
            ),
        ],
        [],
    )
    status, tags = columns
    assert status.default == str(status.options[0].id)
    assert status.options[0].color == "blue"
    assert tags.default == [str(option.id) for option in tags.options]
    assert tags.options[1].color == "yellow"
    changed = build_columns(
        [
            ColumnInput(
                id=status.id,
                label="Status",
                type="single_select",
                options=[OptionInput(id=status.options[0].id, label="Todo")],
                default=status.default,
            )
        ],
        [status],
    )[0]
    assert changed.options[0].color == "blue"
    assert changed.options[1].archived
    assert changed.options[1].color == "green"
    reset = build_columns(
        [
            ColumnInput(
                id=status.id,
                label="Status",
                type="single_select",
                options=[OptionInput(id=status.options[0].id, label="Todo", color=None)],
                default=None,
            )
        ],
        [status],
    )[0]
    assert reset.options[0].color is None


def test_default_option_ids_take_precedence_over_colliding_labels() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    previous = ColumnDef(
        id=uuid.uuid4(),
        label="Status",
        type="single_select",
        options=[OptionDef(id=first, label="First"), OptionDef(id=second, label=str(first))],
    )
    (column,) = build_columns(
        [
            ColumnInput(
                id=previous.id,
                label="Status",
                type="single_select",
                default=str(first),
                options=[
                    OptionInput(id=first, label="First"),
                    OptionInput(id=second, label=str(first)),
                ],
            )
        ],
        [previous],
    )
    assert column.default == str(first)


def test_an_unknown_default_option_label_is_refused() -> None:
    with pytest.raises(InvalidSchemaError):
        build_columns(
            [
                ColumnInput(
                    label="Status",
                    type="single_select",
                    options=[OptionInput(label="Todo")],
                    default="Unknown",
                )
            ],
            [],
        )


@pytest.mark.parametrize("name", ["created_at", "updated_at", "created_by", "updated_by"])
def test_record_metadata_names_belong_to_system_fields(name: str) -> None:
    with pytest.raises(InvalidSchemaError):
        build_columns([ColumnInput(label=name, type="text")], [])


def test_initial_required_column_does_not_need_a_default():
    (column,) = build_columns(
        [ColumnInput(label="Contact ID", type="text", nullable=False)], [], initial=True
    )
    assert column.nullable is False
    assert column.default is None


def test_schema_extension_still_requires_a_default_for_required_columns():
    with pytest.raises(InvalidSchemaError, match="needs a default"):
        build_columns([ColumnInput(label="Contact ID", type="text", nullable=False)], [_existing()])
