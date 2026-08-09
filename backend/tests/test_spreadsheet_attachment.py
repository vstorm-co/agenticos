"""Attaching a spreadsheet to a chat.

`.xlsx` used to be refused at the gate - "File type '…spreadsheetml.sheet' is not
supported" - and the obvious fix, adding the type to the allowed set, would have
been worse than the refusal. The reason is the whole of this module: **an agent
cannot open a workbook.** `run_python` has no filesystem, it is for arithmetic;
the workspace shell has no spreadsheet library; and `read_file` on a zip of XML
returns mojibake. So a spreadsheet accepted but not parsed reaches an agent with a
workspace as bytes it has no tool for, and an agent without one as nothing at all.

Which makes the parse the feature, and these the tests for it.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from openpyxl import Workbook

from app.services.file_storage import ALLOWED_MIME_TYPES, classify_file
from app.services.file_upload import FileUploadService

pytestmark = pytest.mark.anyio

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSM = "application/vnd.ms-excel.sheet.macroEnabled.12"


def _workbook(sheets: dict[str, list[list[Any]]]) -> bytes:
    """A real `.xlsx`, because the parser is openpyxl and a fake proves nothing."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class TestTheGate:
    def test_a_workbook_is_accepted(self):
        assert XLSX in ALLOWED_MIME_TYPES
        assert XLSM in ALLOWED_MIME_TYPES

    def test_the_old_excel_format_is_still_refused(self):
        """`.xls` is a different format needing a different reader. Accepting it
        on the strength of the name would be the defect this module opens on."""
        assert "application/vnd.ms-excel" not in ALLOWED_MIME_TYPES

    def test_a_workbook_is_its_own_kind_and_not_text(self):
        """Classified as text it would be decoded as UTF-8, and the workspace
        would not know to write the extraction beside it."""
        assert classify_file(XLSX, "vocab.xlsx") == "spreadsheet"
        assert classify_file(XLSM, "vocab.xlsm") == "spreadsheet"

    def test_the_extension_is_enough_when_the_browser_says_nothing_useful(self):
        assert classify_file("application/octet-stream", "vocab.xlsx") == "spreadsheet"


class TestReadingAWorkbook:
    def test_every_sheet_is_read_and_named(self):
        """The data is usually not on the first sheet - that one is a cover or an
        index - so a reader that took the active sheet alone would answer
        questions about a file it had half read."""
        data = _workbook(
            {
                "Cover": [["Hiszpanski od zera do B1"]],
                "Wokabularz": [["slowo", "tlumaczenie"], ["casa", "house"]],
            }
        )

        text = FileUploadService._parse_spreadsheet_content(data)

        assert text == (
            "Sheet: Cover\nHiszpanski od zera do B1\n\n"
            "Sheet: Wokabularz\nslowo\ttlumaczenie\ncasa\thouse"
        )

    def test_rows_are_tab_separated(self):
        """Not commas: a cell holding "1,5" is a number in half of Europe, and
        comma-separating those rows produces a table with a column that appears
        and disappears down the page."""
        data = _workbook({"Prices": [["item", "cost"], ["kawa", "1,50"]]})

        text = FileUploadService._parse_spreadsheet_content(data)

        assert text is not None
        assert "kawa\t1,50" in text

    def test_an_empty_row_is_dropped(self):
        data = _workbook({"S": [["a"], [None], ["b"]]})

        assert FileUploadService._parse_spreadsheet_content(data) == "Sheet: S\na\nb"

    def test_trailing_empty_cells_are_dropped(self):
        """A sheet whose used range is wider than its data - which is most of
        them, after a column has been cleared - would otherwise contribute rows
        of tabs, and those cost tokens to say nothing."""
        data = _workbook({"S": [["a", None, None]]})

        assert FileUploadService._parse_spreadsheet_content(data) == "Sheet: S\na"

    def test_a_gap_inside_a_row_is_kept(self):
        """Only the trailing ones go. A hole in the middle is which column the
        value is in, and closing it moves every cell after it left."""
        data = _workbook({"S": [["a", None, "c"]]})

        assert FileUploadService._parse_spreadsheet_content(data) == "Sheet: S\na\t\tc"

    def test_numbers_and_dates_come_through_as_text(self):
        data = _workbook({"S": [["count", 42], ["ratio", 1.5]]})

        text = FileUploadService._parse_spreadsheet_content(data)

        assert text is not None
        assert "count\t42" in text
        assert "ratio\t1.5" in text

    def test_an_empty_workbook_has_no_text_rather_than_a_heading(self):
        """None, not "Sheet: S" - `make_preview` and the attachment planner both
        read this as "nothing was extracted", and a heading alone would be
        attached to a model as though it were content."""
        assert FileUploadService._parse_spreadsheet_content(_workbook({"S": []})) is None

    def test_something_that_is_not_a_workbook_is_not_an_error(self):
        """A file whose name says `.xlsx` and whose bytes disagree. The upload has
        already been accepted by then, so raising here would lose the file rather
        than the parse."""
        assert FileUploadService._parse_spreadsheet_content(b"not a workbook at all") is None


class TestTheDispatch:
    async def test_the_parser_is_reached_through_the_file_type(self):
        data = _workbook({"S": [["a", "b"]]})

        text = await FileUploadService(db=None).parse_content(data, "spreadsheet", XLSX)  # ty: ignore[invalid-argument-type]

        assert text == "Sheet: S\na\tb"
