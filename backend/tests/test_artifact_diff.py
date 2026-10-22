"""How two versions' page queries are compared, and what each difference is marked (#1974)."""

from __future__ import annotations

from uuid import NAMESPACE_OID, UUID, uuid5

from app.schemas.artifact import (
    ArtifactBinding,
    BindingParts,
    BindingReach,
    DisclosedDerivation,
    DisclosedField,
    DisclosedFilter,
    DisclosedSort,
)
from app.schemas.virtual_table import RecordFilter, RecordSort
from app.services.artifact_diff import BindingView, diff_bindings


def _id(name: str, *, as_of: str = "") -> UUID:
    """The id a table or column of this name has: the same name is the same one, unless
    `as_of` says it is another that happens to be called so."""
    return uuid5(NAMESPACE_OID, f"{as_of}:{name}")


def _field(name: str, column: str | None = None, *, derived: bool = False) -> DisclosedField:
    return DisclosedField(
        name=name,
        column=column or name.title(),
        type="number",
        derived=DisclosedDerivation(kind="formula", inputs=["A"]) if derived else None,
    )


def _parts(
    *,
    table: str = "Orders",
    fields: list[DisclosedField] | None = None,
    filters: list[DisclosedFilter] | None = None,
    sort: DisclosedSort | None = None,
    limit: int = 100,
    linked: list[str] | None = None,
) -> BindingParts:
    return BindingParts(
        table=table,
        filters=filters or [],
        sort=sort or DisclosedSort(record_time="created_at", direction="asc"),
        limit=limit,
        fields=fields if fields is not None else [_field("customer")],
        linked=linked or [],
    )


def _view(parts: BindingParts | None = None, *, of: str = "") -> BindingView:
    """The stored query behind `parts`: every id from a name, so what reads the same has
    the same ids. `of` makes them another generation's - tables and columns of the same
    names that are not the same ones."""
    parts = parts or _parts()
    table_id = _id(parts.table, as_of=of)
    columns = {item.column: _id(item.column, as_of=of) for item in parts.fields}
    columns |= {item.column: _id(item.column, as_of=of) for item in parts.filters}
    if parts.sort.column is not None:
        columns[parts.sort.column] = _id(parts.sort.column, as_of=of)
    linked = {_id(name, as_of=of): name for name in parts.linked}
    sort_by = parts.sort.record_time or columns[parts.sort.column or ""]
    binding = ArtifactBinding(
        name="orders",
        table_id=table_id,
        filters=[
            RecordFilter(column_id=columns[item.column], op=item.op, value=item.value)
            for item in parts.filters
        ],
        sort=RecordSort(by=str(sort_by), direction=parts.sort.direction),
        limit=parts.limit,
        fields={item.name: columns[item.column] for item in parts.fields},
        reach=BindingReach(
            tables={table_id: dict.fromkeys(columns.values(), 0)}
            | {linked_id: {} for linked_id in linked}
        ),
    )
    return BindingView(
        binding=binding,
        parts=parts,
        tables={table_id: parts.table} | linked,
        columns={column_id: label for label, column_id in columns.items()},
    )


def _one(old: BindingParts | BindingView, new: BindingParts | BindingView):
    old = old if isinstance(old, BindingView) else _view(old)
    new = new if isinstance(new, BindingView) else _view(new)
    reviews, unchanged = diff_bindings({"orders": old}, {"orders": new})
    assert unchanged == [] and len(reviews) == 1
    return reviews[0]


class TestWhichBindingsDiffer:
    def test_a_binding_that_reads_the_same_is_collapsed_into_unchanged(self) -> None:
        reviews, unchanged = diff_bindings({"orders": _view()}, {"orders": _view()})
        assert (reviews, unchanged) == ([], ["orders"])

    def test_a_new_binding_widens_and_carries_its_whole_query(self) -> None:
        reviews, unchanged = diff_bindings({}, {"orders": _view()})
        [review] = reviews
        assert (review.change, review.effect, review.parts) == ("added", "widens", _parts())
        assert unchanged == []

    def test_a_dropped_binding_narrows(self) -> None:
        [review] = diff_bindings({"orders": _view()}, {})[0]
        assert (review.change, review.effect) == ("removed", "narrows")
        assert review.parts == _parts()

    def test_bindings_are_reported_by_name(self) -> None:
        reviews, unchanged = diff_bindings(
            {"b": _view(), "a": _view()},
            {"a": _view(), "c": _view(), "b": _view(_parts(limit=5))},
        )
        assert [(r.name, r.change) for r in reviews] == [("b", "changed"), ("c", "added")]
        assert unchanged == ["a"]


class TestWhatEachChangeDoes:
    def test_a_field_added_widens_one_removed_narrows_one_changed_widens(self) -> None:
        review = _one(
            _parts(fields=[_field("customer"), _field("cost"), _field("rate")]),
            _parts(
                fields=[
                    _field("customer"),
                    _field("quantity"),
                    _field("rate", "Salary", derived=True),
                ]
            ),
        )
        assert [(c.aspect, c.change, c.effect) for c in review.changes] == [
            ("field", "added", "widens"),
            ("field", "removed", "narrows"),
            ("field", "changed", "widens"),
        ]
        assert review.effect == "widens"
        changed = review.changes[2]
        assert changed.before == _field("rate") and changed.after == _field(
            "rate", "Salary", derived=True
        )

    def test_a_condition_dropped_widens_and_one_added_narrows(self) -> None:
        was = DisclosedFilter(column="Status", op="eq", value="open")
        now = DisclosedFilter(column="Region", op="eq", value="EU")
        review = _one(_parts(filters=[was]), _parts(filters=[now]))
        assert [(c.aspect, c.change, c.effect) for c in review.changes] == [
            ("filter", "removed", "widens"),
            ("filter", "added", "narrows"),
            ("reach", "added", "widens"),  # the new condition reads a column nothing read
        ]
        assert review.effect == "widens"

    def test_a_condition_left_alone_is_not_a_change(self) -> None:
        kept = DisclosedFilter(column="Status", op="eq", value="open")
        reviews, unchanged = diff_bindings(
            {"orders": _view(_parts(filters=[kept]))}, {"orders": _view(_parts(filters=[kept]))}
        )
        assert (reviews, unchanged) == ([], ["orders"])

    def test_a_changed_operand_widens_unless_a_list_of_choices_only_lost_some(self) -> None:
        def op(value: list[str]) -> DisclosedFilter:
            return DisclosedFilter(column="Status", op="in", value=value)

        widened = _one(_parts(filters=[op(["a"])]), _parts(filters=[op(["a", "b"])]))
        narrowed = _one(_parts(filters=[op(["a", "b"])]), _parts(filters=[op(["a"])]))
        swapped = _one(_parts(filters=[op(["a"])]), _parts(filters=[op(["b"])]))
        scalar = _one(
            _parts(filters=[DisclosedFilter(column="Qty", op="gt", value=1)]),
            _parts(filters=[DisclosedFilter(column="Qty", op="gt", value=5)]),
        )
        assert [r.changes[0].effect for r in (widened, narrowed, swapped, scalar)] == [
            "widens",
            "narrows",
            "widens",
            "widens",
        ]
        assert narrowed.changes[0].change == "changed"

    def test_a_larger_limit_widens_and_a_smaller_one_narrows(self) -> None:
        bigger = _one(_parts(limit=10), _parts(limit=20))
        smaller = _one(_parts(limit=20), _parts(limit=10))
        assert (bigger.effect, smaller.effect) == ("widens", "narrows")
        assert (bigger.changes[0].before, bigger.changes[0].after) == (10, 20)

    def test_another_order_widens_as_it_picks_other_records_into_the_limit(self) -> None:
        review = _one(_parts(), _parts(sort=DisclosedSort(column="Salary", direction="desc")))
        assert [(c.aspect, c.effect) for c in review.changes] == [
            ("sort", "widens"),
            ("reach", "widens"),  # and it reads a column nothing did
        ]
        assert review.effect == "widens"
        flipped = _one(
            _parts(), _parts(sort=DisclosedSort(record_time="created_at", direction="desc"))
        )
        assert (flipped.changes[0].aspect, flipped.effect) == ("sort", "widens")

    def test_a_column_read_only_by_a_condition_widens_though_no_field_shows_it(self) -> None:
        review = _one(
            _parts(),
            _parts(filters=[DisclosedFilter(column="Salary", op="gt", value=1)]),
        )
        assert [(c.aspect, c.change, c.effect, c.after) for c in review.changes] == [
            ("filter", "added", "narrows", DisclosedFilter(column="Salary", op="gt", value=1)),
            ("reach", "added", "widens", "Salary"),
        ]
        assert review.effect == "widens"

    def test_a_table_and_columns_are_the_same_only_by_id_not_by_name(self) -> None:
        """A binding moved from an archived Payroll to a new live one of the same name."""
        parts = _parts(table="Payroll", fields=[_field("pay", "Salary")])
        review = _one(_view(parts), _view(parts, of="live"))
        assert [(c.aspect, c.change, c.effect) for c in review.changes] == [
            ("table", "changed", "widens"),
            ("field", "changed", "widens"),
        ]
        assert (review.changes[0].before, review.changes[0].after) == ("Payroll", "Payroll")
        assert review.effect == "widens"

    def test_a_linked_table_is_the_same_only_by_id(self) -> None:
        was = _view(_parts(linked=["Deals"]))
        now = _view(_parts(linked=["Deals"]), of="live")
        review = _one(was, now)
        assert [(c.aspect, c.change, c.effect) for c in review.changes if c.aspect == "linked"] == [
            ("linked", "added", "widens"),
            ("linked", "removed", "narrows"),
        ]

    def test_a_filter_on_another_column_of_the_same_name_is_another_condition(self) -> None:
        condition = [DisclosedFilter(column="Status", op="eq", value="open")]
        was = _view(_parts(filters=condition))
        moved = RecordFilter(column_id=_id("Status", as_of="live"), op="eq", value="open")
        now = was._replace(binding=was.binding.model_copy(update={"filters": [moved]}))
        review = _one(was, now)
        assert [(c.aspect, c.change, c.effect) for c in review.changes] == [
            ("filter", "removed", "widens"),
            ("filter", "added", "narrows"),
        ]

    def test_a_linked_table_added_widens_and_one_dropped_narrows(self) -> None:
        review = _one(_parts(linked=["Deals"]), _parts(linked=["Customers"]))
        assert [(c.change, c.effect, c.before or c.after) for c in review.changes] == [
            ("added", "widens", "Customers"),
            ("removed", "narrows", "Deals"),
        ]

    def test_another_table_widens(self) -> None:
        review = _one(_parts(), _parts(table="Salaries"))
        assert (review.changes[0].aspect, review.effect) == ("table", "widens")

    def test_a_binding_that_only_narrows_is_marked_so(self) -> None:
        review = _one(_parts(limit=20), _parts(limit=10))
        assert review.effect == "narrows"
