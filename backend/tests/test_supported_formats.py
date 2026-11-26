"""The advertised file formats and the ones the pipeline can route must agree.

Three lists used to disagree. `PARSER_FORMATS` told
`GET /rag/supported-formats` - and through it the upload UI - that LiteParse
read `.xlsx`/`.pptx`/images and that LlamaParse read thirty formats down to
`.mp3`. `RAGDocumentService.upload` validated against that same list, so the
upload was accepted: the file was stored, a `RAGDocument` row was committed and
the ingestion task was dispatched. Only then, in a worker, did
`DocumentProcessor.process_file` reach its `else` branch and raise
`ValueError: Unsupported file type: .xlsx` - for a document that by that point
existed, was listed, and had no way of saying why it never finished.

A refusal at the door is fine. A promise the pipeline cannot keep is not, and the
gap is invisible in review because the three lists live in two modules. These
tests are the seam: widen a format set without teaching a parser to read it, and
this fails rather than somebody's upload.

`app/services/rag/*` is template-inherited and sits outside the coverage gate,
so nothing else here would have caught it.
"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.services.rag.config import (
    LITEPARSE_FORMATS,
    LITEPARSE_IMAGE_FORMATS,
    LITEPARSE_OFFICE_FORMATS,
    LLAMAPARSE_FORMATS,
    NATIVE_FORMATS,
    PARSER_FORMATS,
    PYMUPDF_FORMATS,
    PdfParser,
    RAGSettings,
    get_supported_formats,
)
from app.services.rag.documents import (
    DocumentProcessor,
    LiteParseParser,
    LlamaParseParser,
    PdfParserFactory,
    PyMuPDFParser,
    has_indexable_text,
)
from app.services.rag.models import Document, DocumentMetadata, DocumentPage

pytestmark = pytest.mark.anyio

# The class each parser name resolves to in `PdfParserFactory.create`. Held as
# classes, not instances: `LiteParseParser` and `LlamaParseParser` import their
# optional SDKs inside `__init__`, and neither is needed to answer what the
# parser reads - `allowed` is a class attribute precisely so this test does not
# depend on installing them.
PARSER_CLASSES: dict[str, type] = {
    "pymupdf": PyMuPDFParser,
    "liteparse": LiteParseParser,
    "llamaparse": LlamaParseParser,
}


@pytest.mark.parametrize("parser_name", sorted(PARSER_FORMATS))
def test_every_advertised_format_is_routable(parser_name: str) -> None:
    """Nothing the API accepts may reach `process_file` and fall through.

    `process_file` routes an extension one of two ways: to a Python-native
    parser, or to the configured PDF parser when that parser accepts it. Any
    advertised extension outside that union is an upload that gets stored and
    then dies in a worker.
    """
    routable = NATIVE_FORMATS | set(PARSER_CLASSES[parser_name].allowed)
    unroutable = PARSER_FORMATS[parser_name] - routable
    assert not unroutable, (
        f"{parser_name} advertises {sorted(unroutable)}, which process_file cannot route"
    )


@pytest.mark.parametrize("parser_name", sorted(PARSER_FORMATS))
def test_nothing_readable_is_refused_at_the_door(parser_name: str) -> None:
    """The converse: a parser that reads a format the API refuses is dead capability.

    Less damaging than the other direction - the user is told no rather than
    misled - but it is still the two lists drifting apart, and it is how the
    LlamaParse extras came to be unreachable for as long as they were.
    """
    unadvertised = set(PARSER_CLASSES[parser_name].allowed) - PARSER_FORMATS[parser_name]
    assert not unadvertised, (
        f"{parser_name} reads {sorted(unadvertised)}, which the upload endpoint refuses"
    )


def test_native_formats_are_offered_by_every_parser() -> None:
    """Choosing a PDF parser must never cost you plain text.

    Text and Markdown are read by the built-in reader whatever the parser is set
    to, so every parser's set contains them. Every other format goes to the
    chosen parser, `.docx` included.
    """
    assert {".txt", ".md"} == NATIVE_FORMATS
    for parser_name, formats in PARSER_FORMATS.items():
        assert formats >= NATIVE_FORMATS, f"{parser_name} drops a natively-read format"


def test_liteparse_claims_both_conversion_paths() -> None:
    """LiteParse converts to PDF before parsing, by two different routes.

    Verified against the parser rather than assumed: a `.csv` (LibreOffice) and
    a `.png` (native, OCR on) both come back with their text. Pinned here so a
    future narrowing of the set has to be deliberate.
    """
    assert LITEPARSE_IMAGE_FORMATS <= LITEPARSE_FORMATS
    assert LITEPARSE_OFFICE_FORMATS <= LITEPARSE_FORMATS
    assert ".pdf" in LITEPARSE_FORMATS


def test_office_formats_need_libreoffice_and_images_do_not() -> None:
    """The split between the two sets is what makes the failure explainable.

    Office conversion shells out to LibreOffice; image conversion is native Rust
    since liteparse v2.8.0. Only the first can be missing at runtime, and
    `LiteParseParser.parse` refuses those by name rather than letting the Rust
    core return a conversion error nobody can act on.
    """
    assert LITEPARSE_IMAGE_FORMATS.isdisjoint(LITEPARSE_OFFICE_FORMATS)
    assert ".pdf" not in LITEPARSE_OFFICE_FORMATS


@pytest.mark.parametrize("content", ["```text\n\n```", "   ", "``", ""])
def test_a_page_of_markdown_scaffolding_is_not_text(content: str) -> None:
    """An unreadable scan comes back as an empty fenced block, not as whitespace.

    `.strip()` keeps it, so it used to be embedded as a chunk that says nothing
    and matches nothing - the whole document looking ingested and answering no
    question.
    """
    assert not has_indexable_text(content)


def test_real_content_survives_the_same_filter() -> None:
    assert has_indexable_text("# Heading\n\nRevenue grew 12 percent.")
    assert has_indexable_text("```python\nx = 1\n```")


def test_get_supported_formats_refuses_an_unknown_parser() -> None:
    """An unknown parser name is an error, not PyMuPDF's formats under another name.

    Parser selection never falls back silently: `PdfParserFactory.create` raises on
    a name it does not know, so the formats an upload is checked against must not
    quietly answer for a parser that would then refuse to be built.
    """
    with pytest.raises(KeyError):
        get_supported_formats("something-else")
    assert get_supported_formats() == PYMUPDF_FORMATS
    assert get_supported_formats("llamaparse") == LLAMAPARSE_FORMATS


async def test_process_file_names_the_parser_when_it_cannot_route(tmp_path: Path) -> None:
    """The refusal has to say which parser, or it cannot be acted on.

    A worker log reading "Unsupported file type: .xlsx" leaves the reader to
    guess whether the fix is a different file or a different collection setting.
    """
    spreadsheet = tmp_path / "quarterly.xlsx"
    spreadsheet.write_bytes(b"not really a spreadsheet")

    processor = DocumentProcessor(RAGSettings())

    with pytest.raises(ValueError) as excinfo:
        await processor.process_file(spreadsheet)

    message = str(excinfo.value)
    assert ".xlsx" in message
    assert "PyMuPDFParser" in message
    assert ".pdf" in message


async def test_process_file_routes_a_suffix_case_insensitively(tmp_path: Path) -> None:
    """`.MD` is Markdown. The upload endpoint lower-cases the extension it
    validates, so `process_file` matching case-sensitively would refuse in a
    worker exactly the file the API had just accepted.
    """
    note = tmp_path / "README.MD"
    note.write_text("# Heading\n\nBody text.")

    processor = DocumentProcessor(RAGSettings())
    document = await processor.process_file(note)

    assert document.pages[0].content.startswith("# Heading")


def _docx_with_table(path: Path) -> Path:
    from docx import Document as WordDocument

    document = WordDocument()
    document.add_heading("Report", level=1)
    for number in range(120):
        document.add_paragraph(f"Paragraph {number} of the report.")
    table = document.add_table(rows=3, cols=3)
    for row in range(3):
        for column in range(3):
            table.cell(row, column).text = f"R{row + 1}C{column + 1}"
    document.add_page_break()
    document.add_paragraph("After the break.")
    document.save(str(path))
    return path


@pytest.mark.parametrize("parser_name", ["pymupdf", "liteparse", "llamaparse"])
async def test_docx_goes_to_the_chosen_parser(parser_name: str, tmp_path: Path) -> None:
    """The chosen parser reads every format it claims, `.docx` among them."""
    settings = RAGSettings(pdf_parser=PdfParser(method=parser_name, api_key="k"))
    processor = DocumentProcessor(settings)
    assert ".docx" in processor.pdf_parser.allowed
    parse = AsyncMock(
        return_value=Document(
            pages=[DocumentPage(page_num=1, content="Some text")],
            metadata=DocumentMetadata(filename="m.docx", filesize=1, filetype="docx"),
        )
    )
    processor.pdf_parser.parse = parse  # type: ignore[method-assign]
    path = _docx_with_table(tmp_path / "memo.docx")

    await processor.process_file(path)

    parse.assert_awaited_once_with(path)


async def test_pymupdf_reads_docx_tables(tmp_path: Path) -> None:
    document = await PyMuPDFParser().parse(_docx_with_table(tmp_path / "memo.docx"))

    assert len(document.pages) > 1
    assert "R1C1" in "\n".join(page.content for page in document.pages)


async def test_ooxml_bound_applies_before_any_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_: bytes) -> bytes:
        raise ValueError("too large")

    monkeypatch.setattr("app.services.rag.documents.safe_unzip", refuse)
    processor = DocumentProcessor(RAGSettings(pdf_parser=PdfParser(method="liteparse")))
    parse = AsyncMock()
    processor.pdf_parser.parse = parse  # type: ignore[method-assign]
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"PK")

    with pytest.raises(ValueError, match="too large"):
        await processor.process_file(deck)

    parse.assert_not_awaited()


def test_unknown_parser_name_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown parser 'nope'"):
        PdfParserFactory.create("nope")
