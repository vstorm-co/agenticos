"""The shared export primitives: the machinery two export domains lean on.

A spreadsheet reads a leading `=` as a formula, a bulk read has no natural
ceiling, a date range must be given rather than assumed. These are the same
whichever domain is being exported, so they are tested once, here, rather than
in each export's own suite.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.exceptions import ExportTooLargeError, ValidationError
from app.services import exporting

_WHEN = datetime(2026, 8, 1, tzinfo=UTC)


class TestCsvCells:
    def test_a_formula_leading_cell_is_neutralised(self):
        """A cell opening on `=` is a formula in a spreadsheet, so it is quoted."""
        assert exporting.escape("=cmd()") == "'=cmd()"

    def test_a_plain_cell_is_left_alone(self):
        assert exporting.escape("openai") == "openai"

    def test_an_empty_string_is_left_alone(self):
        assert exporting.escape("") == ""

    def test_a_negative_number_stays_summable(self):
        """A leading `-` is a formula prefix only on a string; a number keeps it,
        so a credit exports as `-1.50` a spreadsheet sums rather than quoted text."""
        assert exporting.cell(Decimal("-1.50")) == "-1.50"

    def test_none_is_an_empty_cell_not_the_word_none(self):
        assert exporting.cell(None) == ""

    def test_a_bool_is_lowercase_words(self):
        assert (exporting.cell(True), exporting.cell(False)) == ("true", "false")

    def test_a_datetime_is_iso(self):
        assert exporting.cell(_WHEN) == "2026-08-01T00:00:00+00:00"

    def test_another_type_is_stringified(self):
        assert exporting.cell(42) == "42"


class TestCsvDocument:
    def test_the_header_leads_and_rows_follow(self):
        doc = exporting.csv_document(["a", "b"], [[1, "x"], [2, "y"]])
        assert doc.splitlines() == ["a,b", "1,x", "2,y"]


class TestJsonlDocument:
    def test_one_object_per_line_with_a_trailing_newline(self):
        doc = exporting.jsonl_document([{"a": 1}, {"a": 2}])
        assert doc == '{"a": 1}\n{"a": 2}\n'

    def test_no_records_is_an_empty_string_not_a_lone_newline(self):
        assert exporting.jsonl_document([]) == ""

    def test_stored_types_render_as_the_csv_renders_them(self):
        """A datetime, a UUID and a Decimal all become strings, so the two
        documents describe one row the same way."""
        entry_id = uuid.uuid4()
        doc = exporting.jsonl_document([{"id": entry_id, "when": _WHEN, "cost": Decimal("1.50")}])
        assert f'"id": "{entry_id}"' in doc
        assert '"when": "2026-08-01T00:00:00+00:00"' in doc
        assert '"cost": "1.50"' in doc

    def test_an_unserialisable_value_is_a_bug_not_a_silent_coercion(self):
        with pytest.raises(TypeError):
            exporting.jsonl_document([{"x": object()}])


class TestRequireRange:
    def test_both_bounds_present_pass_through(self):
        assert exporting.require_range(_WHEN, _WHEN) == (_WHEN, _WHEN)

    def test_a_missing_bound_is_named(self):
        with pytest.raises(ValidationError) as excinfo:
            exporting.require_range(None, _WHEN)
        assert excinfo.value.details == {"missing": ["from"]}

    def test_both_missing_are_named(self):
        with pytest.raises(ValidationError) as excinfo:
            exporting.require_range(None, None)
        assert excinfo.value.details == {"missing": ["from", "to"]}

    def test_a_reversed_range_is_refused(self):
        """`from` after `to` is an impossible predicate - it would return a
        silently-empty file and record a misleading export, so it is refused."""
        earlier = _WHEN - timedelta(days=1)
        with pytest.raises(ValidationError):
            exporting.require_range(_WHEN, earlier)

    def test_a_zero_width_range_is_allowed(self):
        # `from == to` is a valid instant-wide window, not a reversal.
        assert exporting.require_range(_WHEN, _WHEN) == (_WHEN, _WHEN)


class TestGuardCap:
    def test_a_match_within_the_cap_is_allowed(self):
        exporting.guard_cap(exporting.MAX_EXPORT_ROWS, remedy="Narrow it.")

    def test_a_match_over_the_cap_is_refused_with_both_numbers(self):
        over = exporting.MAX_EXPORT_ROWS + 1
        with pytest.raises(ExportTooLargeError) as excinfo:
            exporting.guard_cap(over, remedy="Narrow the date range.")
        assert excinfo.value.details == {
            "row_count": over,
            "max_rows": exporting.MAX_EXPORT_ROWS,
        }
        assert "Narrow the date range." in excinfo.value.message


class TestStamp:
    def test_the_name_carries_the_kind_the_instant_and_the_extension(self):
        assert exporting.stamp("audit", _WHEN, "jsonl") == "audit_export_20260801_000000.jsonl"
