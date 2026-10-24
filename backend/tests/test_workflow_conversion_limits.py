"""File conversion limits reject expansion before a full output is materialized."""

from unittest.mock import MagicMock

import pytest

from app.workflows.nodes import _documents, _files


def test_csv_column_discovery_stops_a_sparse_quadratic_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_files, "MAX_CSV_CELLS", 100)
    with pytest.raises(_files.ParseError, match="columns or cells"):
        _files.csv_text([{f"column_{i}": i} for i in range(11)])


def test_csv_byte_limit_counts_encoded_unicode_and_keeps_the_exact_boundary() -> None:
    assert _files.csv_text([{"é": "é"}], max_bytes=6) == "é\né\n"
    with pytest.raises(_files.ParseError, match="byte limit"):
        _files.csv_text([{"é": "é"}], max_bytes=5)


def test_csv_refuses_excess_rows_before_reading_them(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_files, "MAX_CSV_ROWS", 1)
    with pytest.raises(_files.ParseError, match="rows"):
        _files.csv_text([{"x": 1}, {"x": 2}])


def test_pdf_page_limit_is_checked_before_text_is_extracted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = MagicMock(page_count=_documents.MAX_PDF_PAGES + 1)
    monkeypatch.setattr(_documents, "_open_pdf", lambda _: document)
    with pytest.raises(_documents.DocumentTooLarge, match="pages"):
        _documents.pdf_text(b"document", max_chars=10)
    document.__getitem__.assert_not_called()
    document.close.assert_called_once()


@pytest.mark.security
def test_pdf_stops_reading_pages_as_soon_as_the_character_budget_is_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = MagicMock(page_count=3)
    document.__getitem__.return_value.get_text.return_value = "12345"
    monkeypatch.setattr(_documents, "_open_pdf", lambda _: document)
    with pytest.raises(_documents.DocumentTextTooLong):
        _documents.pdf_text(b"document", max_chars=4)
    document.__getitem__.assert_called_once_with(0)
    document.close.assert_called_once()


def test_csv_reader_refuses_excess_columns_before_materializing_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_files, "MAX_CSV_COLUMNS", 2)
    with pytest.raises(_files.ParseError, match="columns"):
        _files.csv_rows("a,b,c\n1,2,3\n")


def test_csv_reader_refuses_excess_cells_before_materializing_the_next_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_files, "MAX_CSV_CELLS", 3)
    with pytest.raises(_files.ParseError, match="rows or cells"):
        _files.csv_rows("a,b\n1,2\n3,4\n")


def test_csv_to_json_refuses_output_expansion_before_a_file_is_stored() -> None:
    from app.workflows.nodes.convert_csv_to_json._handler import _convert

    with pytest.raises(_files.ParseError, match="byte limit"):
        _convert(b"long-column-name\n1\n2\n", 20)


def test_large_file_sniffing_never_parses_the_complete_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workflows import files

    monkeypatch.setattr(files.json, "loads", lambda _: pytest.fail("parsed the large file"))
    assert files.sniff(b"[0," + b"0," * 10_000 + b"0]") == "application/json"
    assert files.sniff(b"a" * 10_000) == "text/plain"
    assert (
        files.sniff(b"a" * (files._SNIFF_BYTES - 1) + "é".encode() + b"a" * 1_000) == "text/plain"
    )


def test_url_filenames_cannot_carry_a_nul_to_the_database() -> None:
    from app.workflows.nodes.http_download._handler import _filename_from

    assert _filename_from("https://example.com/report%00.txt") == "report.txt"
    assert _filename_from("https://example.com/%00") is None
