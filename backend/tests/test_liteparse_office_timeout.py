"""How `LiteParseParser` routes office formats through the owned converter (#1685).

Office documents are converted to PDF by `app.core.office_convert`, whose
subprocess we can kill on timeout, and then read as PDFs; everything else goes
straight to LiteParse's native pipeline. These tests pin the routing and the way
a conversion failure is turned into a parse error whose message names the upload,
never the temporary file it was handed - the rule a stored `error_message` lives
by (#423).
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from app.core.office_convert import OfficeConversionError, OfficeConversionTimeout
from app.services.rag import documents
from app.services.rag.documents import LiteParseParser

pytestmark = pytest.mark.anyio


async def test_an_office_conversion_timeout_becomes_a_named_parse_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(LiteParseParser, "_libreoffice", True)

    async def timeout(*_args: object, **_kwargs: object) -> Path:
        raise OfficeConversionTimeout("Converting report.docx to PDF exceeded 600s")

    monkeypatch.setattr(documents, "convert_to_pdf", timeout)
    source = tmp_path / "report.docx"
    source.write_bytes(b"x")

    with pytest.raises(RuntimeError) as excinfo:
        await LiteParseParser(timeout_seconds=600.0).parse(source)

    message = str(excinfo.value)
    assert "report.docx" in message
    assert "600" in message
    assert "liteparse-office-" not in message
    assert tempfile.gettempdir() not in message


async def test_an_office_conversion_failure_becomes_a_named_parse_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(LiteParseParser, "_libreoffice", True)

    async def fail(*_args: object, **_kwargs: object) -> Path:
        raise OfficeConversionError("LibreOffice could not convert report.doc to PDF")

    monkeypatch.setattr(documents, "convert_to_pdf", fail)
    source = tmp_path / "report.doc"
    source.write_bytes(b"x")

    with pytest.raises(RuntimeError) as excinfo:
        await LiteParseParser().parse(source)

    message = str(excinfo.value)
    assert "report.doc" in message
    assert "convert" in message.lower()


async def test_an_office_format_without_libreoffice_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-existing refusal survives the refactor: named format, apt-get hint."""
    monkeypatch.setattr(LiteParseParser, "_libreoffice", False)
    source = tmp_path / "sheet.ods"
    source.write_bytes(b"x")

    with pytest.raises(RuntimeError) as excinfo:
        await LiteParseParser().parse(source)

    message = str(excinfo.value)
    assert ".ods" in message
    assert "apt-get install libreoffice" in message


async def test_a_pdf_is_parsed_natively_without_touching_libreoffice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-office formats must never reach the converter."""

    async def tripwire(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("convert_to_pdf must not run for a PDF")

    monkeypatch.setattr(documents, "convert_to_pdf", tripwire)
    sentinel = object()

    async def fake_parse_pdf(
        _self: LiteParseParser, parse_target: Path, *, source: Path, timeout: float | None = None
    ) -> object:
        assert parse_target == source
        assert timeout is None
        return sentinel

    monkeypatch.setattr(LiteParseParser, "_parse_pdf", fake_parse_pdf)

    result = await LiteParseParser().parse(tmp_path / "manual.pdf")

    assert result is sentinel


async def test_an_office_file_is_read_as_the_converted_pdf_but_keeps_its_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The PDF is what LiteParse reads; the original name/type is the metadata."""
    monkeypatch.setattr(LiteParseParser, "_libreoffice", True)
    converted = tmp_path / "converted.pdf"

    async def convert(source: Path, out_dir: Path, *, timeout_seconds: float) -> Path:
        assert out_dir.exists()
        return converted

    monkeypatch.setattr(documents, "convert_to_pdf", convert)
    seen: dict[str, Path] = {}

    async def fake_parse_pdf(
        _self: LiteParseParser, parse_target: Path, *, source: Path, timeout: float | None = None
    ) -> object:
        seen["target"] = parse_target
        seen["source"] = source
        return object()

    monkeypatch.setattr(LiteParseParser, "_parse_pdf", fake_parse_pdf)
    source = tmp_path / "board.pptx"
    source.write_bytes(b"x")

    await LiteParseParser().parse(source)

    assert seen["target"] == converted
    assert seen["source"] == source


async def test_the_conversion_and_parse_share_one_timeout_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`timeout_seconds` bounds the whole document, not conversion and parse each.

    A conversion that spends part of the budget must leave the native parse only
    what remains, so the total wait stays under the configured ceiling (#1685).
    """
    monkeypatch.setattr(LiteParseParser, "_libreoffice", True)
    converted = tmp_path / "converted.pdf"

    async def slow_convert(source: Path, out_dir: Path, *, timeout_seconds: float) -> Path:
        await asyncio.sleep(0.2)
        return converted

    monkeypatch.setattr(documents, "convert_to_pdf", slow_convert)
    seen: dict[str, float | None] = {}

    async def fake_parse_pdf(
        _self: LiteParseParser, parse_target: Path, *, source: Path, timeout: float | None = None
    ) -> object:
        seen["timeout"] = timeout
        return object()

    monkeypatch.setattr(LiteParseParser, "_parse_pdf", fake_parse_pdf)
    source = tmp_path / "board.pptx"
    source.write_bytes(b"x")

    await LiteParseParser(timeout_seconds=1.0).parse(source)

    assert seen["timeout"] is not None
    assert 0.0 < seen["timeout"] < 1.0
