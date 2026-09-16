"""Resolving a canonical format, a coarse file_type and a canonical MIME (#1591).

The declared MIME cannot be trusted alone — an `application/octet-stream` `.tiff`
must still reach the PNG path and a `.xls` the xlrd branch — so a canonical format is
resolved from MIME + extension, and the *resolved* MIME is what is persisted.
"""

from __future__ import annotations

import io

import pytest

from app.services.file_storage import canonical_mime, classify_file, resolve_format
from app.services.file_upload import FileUploadService

pytestmark = pytest.mark.anyio

OCTET = "application/octet-stream"


class TestClassification:
    @pytest.mark.parametrize(
        ("mime", "filename", "expected"),
        [
            ("application/msword", "m.doc", "document"),
            ("application/vnd.oasis.opendocument.text", "n.odt", "document"),
            ("application/vnd.ms-excel", "b.xls", "spreadsheet"),
            ("application/vnd.oasis.opendocument.spreadsheet", "b.ods", "spreadsheet"),
            (
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "d.pptx",
                "presentation",
            ),
            ("application/vnd.oasis.opendocument.presentation", "d.odp", "presentation"),
            ("application/vnd.ms-outlook", "e.msg", "email"),
            ("image/tiff", "s.tiff", "image"),
            ("application/xml", "d.xml", "text"),
        ],
    )
    def test_each_format_gets_its_file_type(self, mime, filename, expected):
        assert classify_file(mime, filename) == expected

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("m.doc", "document"),
            ("b.xls", "spreadsheet"),
            ("d.pptx", "presentation"),
            ("e.msg", "email"),
            ("s.tiff", "image"),
            ("n.odt", "document"),
        ],
    )
    def test_the_extension_classifies_when_the_type_says_octet_stream(self, filename, expected):
        assert classify_file(OCTET, filename) == expected


class TestCanonicalMime:
    def test_an_octet_stream_tiff_resolves_to_image_tiff(self):
        assert canonical_mime(OCTET, "scan.tiff") == "image/tiff"

    def test_an_octet_stream_office_file_resolves_to_its_own_type(self):
        assert canonical_mime(OCTET, "m.doc") == "application/msword"
        assert canonical_mime(OCTET, "b.ods") == "application/vnd.oasis.opendocument.spreadsheet"

    def test_an_octet_stream_text_file_resolves_by_extension(self):
        assert canonical_mime(OCTET, "data.xml") == "application/xml"
        assert canonical_mime(OCTET, "notes.csv") == "text/csv"

    def test_a_declared_text_type_is_kept(self):
        assert canonical_mime("text/markdown", "readme.md") == "text/markdown"

    def test_an_unknown_text_extension_falls_back_to_plain(self):
        assert canonical_mime(OCTET, "mystery") == "text/plain"

    def test_a_macro_enabled_workbook_keeps_its_own_mime(self):
        """`.xlsm` shares the `xlsx` format token (one parser, one file type) but must
        not be persisted - and so served on download - as a plain `.xlsx` (#1591)."""
        macro = "application/vnd.ms-excel.sheet.macroEnabled.12"
        assert canonical_mime(OCTET, "book.xlsm") == macro
        assert canonical_mime(macro, "book.xlsm") == macro
        # A plain .xlsx is unaffected.
        assert (
            canonical_mime(OCTET, "book.xlsx")
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    def test_a_macro_enabled_workbook_still_classifies_as_a_spreadsheet(self):
        assert classify_file(OCTET, "book.xlsm") == "spreadsheet"


class TestOctetStreamReachesTheRightParser:
    """The sharp edge of §7 finding 1: an octet-stream file still dispatches to the
    correct parser through the resolved canonical MIME."""

    def _ods(self) -> bytes:
        from odf.opendocument import OpenDocumentSpreadsheet
        from odf.table import Table, TableCell, TableRow
        from odf.text import P

        document = OpenDocumentSpreadsheet()
        table = Table(name="S")
        row = TableRow()
        for value in ("a", "b"):
            cell = TableCell()
            cell.addElement(P(text=value))
            row.addElement(cell)
        table.addElement(row)
        document.spreadsheet.addElement(table)
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    async def test_an_octet_stream_ods_reaches_the_odfpy_parser(self):
        assert resolve_format(OCTET, "book.ods") == "ods"
        resolved = canonical_mime(OCTET, "book.ods")

        text = await FileUploadService(db=None).parse_content(
            self._ods(), "spreadsheet", resolved, "book.ods"
        )

        assert text == "Sheet: S\na\tb"

    async def test_an_octet_stream_xls_reaches_the_xlrd_parser(self):
        from pathlib import Path

        data = (Path(__file__).parent / "fixtures" / "legacy.xls").read_bytes()
        resolved = canonical_mime(OCTET, "legacy.xls")

        text = await FileUploadService(db=None).parse_content(
            data, "spreadsheet", resolved, "legacy.xls"
        )

        assert text is not None and "Sheet: Cover" in text
