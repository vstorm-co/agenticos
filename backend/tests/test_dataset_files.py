"""The dataset file formats: what an import refuses, and what an export promises.

An import is all or nothing and names the rows it refused; an export imports
back unchanged, which is why the spreadsheet formula guard has to be reversible.
"""

import csv
import json
import uuid
from datetime import UTC, datetime

import pytest

from app.core.exceptions import BadRequestError
from app.db.models.dataset import DatasetCase
from app.services import dataset_files
from app.services.dataset_files import COLUMNS, MAX_IMPORT_BYTES, format_of, parse, render

HEADER = ",".join(COLUMNS)
CHECK = '"[{""type"": ""contains"", ""value"": ""x""}]"'


def _case(**fields: object) -> DatasetCase:
    values: dict[str, object] = {
        "history": [],
        "reference_answer": None,
        "counter_example": None,
        "expected_tool_calls": [],
        "order_mode": "any",
        "checks": [],
        "tags": [],
        "note": None,
        **fields,
    }
    return DatasetCase(
        id=uuid.uuid4(),
        case_id=uuid.uuid4(),
        source="manual",
        created_at=datetime.now(UTC),
        **values,
    )


def _refusal(content: str | bytes, fmt: dataset_files.DatasetFileFormat = "csv") -> BadRequestError:
    raw = content.encode() if isinstance(content, str) else content
    with pytest.raises(BadRequestError) as refused:
        parse(raw, fmt)
    return refused.value


class TestFormat:
    def test_the_extension_decides_unless_a_format_is_declared(self) -> None:
        assert format_of("cases.CSV", None) == "csv"
        assert format_of("cases.jsonl", None) == "jsonl"
        assert format_of("cases.ndjson", None) == "jsonl"
        assert format_of("cases.txt", "csv") == "csv"

    def test_a_file_whose_format_cannot_be_told_is_refused(self) -> None:
        with pytest.raises(BadRequestError):
            format_of(None, None)


class TestRoundTrip:
    def test_a_cell_a_spreadsheet_would_evaluate_comes_back_as_it_was(self) -> None:
        cases = [
            _case(input="=SUM(A1)", note="'quoted", reference_answer="-5", tags=["@team"]),
            _case(input="plain", counter_example="+1"),
        ]
        document = render(cases, "csv")

        assert "'=SUM(A1)" in document
        assert "''quoted" in document
        parsed = parse(document.encode(), "csv")
        assert [case.input for case in parsed] == ["=SUM(A1)", "plain"]
        assert parsed[0].note == "'quoted"
        assert parsed[0].reference_answer == "-5"
        assert parsed[0].tags == ["@team"]
        assert parsed[1].counter_example == "+1"
        assert render([_case(**case.model_dump(mode="json")) for case in parsed], "csv") == document

    def test_a_stored_case_that_expects_nothing_still_exports(self) -> None:
        assert render([_case(input="q")], "csv").splitlines()[1].startswith("q,")

    def test_jsonl_keeps_the_structured_fields_as_json(self) -> None:
        case = _case(
            input="q",
            history=[{"role": "user", "content": "before"}],
            expected_tool_calls=[{"tool": "search", "args": {"q": "x"}}],
            order_mode="in_order",
            checks=[{"value": "x", "type": "contains", "path": None}],
            tags=["a"],
        )
        line = json.loads(render([case], "jsonl"))

        assert line["history"] == [{"role": "user", "content": "before"}]
        assert line["order_mode"] == "in_order"
        assert list(line["checks"][0]) == ["type", "path", "value"]
        assert parse(render([case], "jsonl").encode(), "jsonl")[0].tags == ["a"]

    def test_a_byte_order_mark_and_missing_optional_columns_are_fine(self) -> None:
        parsed = parse(b'\xef\xbb\xbfinput,tags,reference_answer\nhello," a , b ",hi\n', "csv")
        assert parsed[0].input == "hello"
        assert parsed[0].tags == ["a", "b"]
        assert parsed[0].order_mode == "any"

    @pytest.mark.parametrize(
        ("cell", "expected"), [("exact", "exact"), (" in_order ", "in_order"), ("", "any")]
    )
    def test_an_empty_order_mode_cell_means_any_order(self, cell, expected) -> None:
        parsed = parse(f"input,order_mode,checks\nq,{cell},{CHECK}\n".encode(), "csv")
        assert parsed[0].order_mode == expected


class TestRefusals:
    def test_one_bad_row_refuses_the_whole_file_and_names_the_row(self) -> None:
        refusal = _refusal(
            "input,order_mode,history,reference_answer\n"
            "fine,any,,a\n"
            ",any,,a\n"
            "q,maybe,,a\n"
            'q,any,"[not json",a\n'
            "q,any,,a,extra\n"
            "q,any,,\n"
        )

        assert refusal.details["refused_rows"] == 5
        fields = {problem["field"] for problem in refusal.details["fields"]}
        assert fields == {
            "rows.2.input",
            "rows.3.order_mode",
            "rows.4",
            "rows.5",
            "rows.6.reference_answer",
        }

    def test_one_refused_row_is_counted_in_the_singular(self) -> None:
        refusal = _refusal("input,order_mode\nq,maybe\n")
        assert refusal.message == "1 row could not be imported, so none were. Fix it and try again."

    def test_the_reported_rows_are_capped(self) -> None:
        refusal = _refusal("input,order_mode\n" + "q,maybe\n" * 30)
        assert refusal.details["refused_rows"] == 30
        assert refusal.message.endswith("Fix them and try again.")
        assert len(refusal.details["fields"]) == 20

    def test_an_unknown_column_or_a_missing_input_is_refused(self) -> None:
        assert "Not a column: id" in _refusal("id,input\n1,q\n").message
        assert _refusal("note\nx\n").details["fields"][0]["field"] == "file"

    def test_a_file_with_no_cases_is_refused(self) -> None:
        assert _refusal(HEADER + "\n").details["fields"][0]["message"] == "The file holds no cases"
        assert _refusal("\n\n", "jsonl").details["fields"][0]["field"] == "file"

    def test_a_file_that_is_not_utf8_or_too_large_is_refused(self) -> None:
        assert "UTF-8" in _refusal(b"input\n\xff\xfe\n").message
        assert "MB" in _refusal(b"x" * (MAX_IMPORT_BYTES + 1)).message

    def test_malformed_csv_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        default = csv.field_size_limit()
        monkeypatch.setattr(dataset_files, "_CELL_LIMIT", 8)
        try:
            refusal = _refusal('input\n"' + "x" * 9 + '"\n')
        finally:
            csv.field_size_limit(default)
        assert "not valid CSV" in refusal.message

    def test_jsonl_lines_that_are_not_case_objects_are_refused(self) -> None:
        refusal = _refusal(
            '{"input": "ok", "reference_answer": "a"}\nnot json\n[1]\n{"input": "q", "id": 1}\n',
            "jsonl",
        )
        assert [problem["field"] for problem in refusal.details["fields"]] == [
            "rows.2",
            "rows.3",
            "rows.4",
        ]
