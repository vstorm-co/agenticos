"""File upload service."""

import codecs
import io
import logging
import re
import zipfile
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.blocking import run_blocking
from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.chat_file import ChatFile
from app.repositories import chat_file as chat_file_repo
from app.services.file_storage import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    canonical_mime,
    classify_file,
    expected_container,
    file_extension,
    get_file_storage,
    has_format_conflict,
    normalize_media_type,
    resolve_format,
    sniff_container,
)
from app.services.office_convert import libreoffice_convert

logger = logging.getLogger(__name__)

PREVIEW_LINES = 3
"""How many lines of a file the upload response carries back.

Enough for a composer card to show what was attached — the first rows of a CSV,
the opening of a pasted stack trace — and no more. This is a label, not a
reader: the file itself is one click away in the preview panel.
"""

PREVIEW_CHARS = 240
"""A second bound, for a file whose three lines are one long line each."""

_ARCHIVE_CHUNK = 1024 * 1024
"""How much of a ZIP member is read at a time when measuring its real size."""

_ODS_MAX_CELLS = 1_000_000
"""How many cells one OpenDocument spreadsheet may expand to across all sheets.

A cell may carry `table:number-columns-repeated`, and the value is attacker-chosen:
a 1.5 KB `.ods` can declare a billion repeats and make `[text] * repeat` allocate an
unbounded list — a post-decompression bomb `safe_unzip` cannot see, because the
expansion is semantic rather than ZIP inflation (#1591, §7 finding 3). Each repeat is
clamped to what is left of this budget, and extraction stops once it is spent; the
bound is far above any real sheet, so trailing empty runs (which are popped anyway)
and genuine data are untouched. `table:number-rows-repeated` is the same trick one
axis over, and is clamped against the same budget.
"""

_XLS_MAX_CELLS = 1_000_000
"""The same rectangular bound as `_ODS_MAX_CELLS`, for the legacy `.xls` sweep.

A sparse BIFF workbook can place one cell at the bottom-right legacy coordinate, so
`sheet.nrows`x`sheet.ncols` describes a 65_536x256 rectangle for a single value.
`ragged_rows=True` stops xlrd padding that rectangle in memory when the workbook is
opened, and this budget bounds the read loop so a handful of such sheets cannot
occupy the bounded file pool before the central text cap runs (#1591).
"""


def make_preview(parsed_content: str | None) -> str | None:
    """The head of a file's extracted text, for a client to render beside its name.

    Derived here rather than in the browser because the browser cannot derive it:
    a PDF or a DOCX is bytes until this service has parsed it, and the client only
    ever holds an id and a filename once the upload has answered. Returning it
    with the upload is also the only version that survives a redraw, where a
    client-side excerpt would be a second source of truth about the same file.

    `None` for anything with no text — an image, or a parse that failed — so a
    card renders its thumbnail or its name alone rather than an empty quote.
    """
    if not parsed_content:
        return None
    head = "\n".join(parsed_content.splitlines()[:PREVIEW_LINES])[:PREVIEW_CHARS].strip()
    return head or None


def cap_text(text: str | None, max_chars: int) -> str | None:
    """Bound extracted text with an explicit truncation marker.

    A small ZIP or OLE upload can expand to very large text; the stored column, the
    preview and the no-workspace paste all read this, so it is capped once here,
    before any of them. The marker names both counts so the model knows the rest
    exists (#1591, §5 #6).
    """
    if text is None or len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n…[truncated {max_chars} of {len(text)} chars]"


def _decode_declared(data: bytes) -> str | None:
    """Decode bytes UTF-8 could not, by their BOM or `<?xml encoding=…?>` declaration.

    UTF-32 is tested before UTF-16 because the UTF-32-LE BOM begins with the
    UTF-16-LE one. Anything with neither a BOM nor a recognisable declaration is
    `None` — a caught, non-fatal failure like every other parser here.
    """
    for bom, encoding in (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if data.startswith(bom):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                return None
    # `\s*` around the `=`: the XML declaration's `Eq` production allows whitespace
    # (`encoding = "windows-1250"`), so a strict `encoding=` missed a legal header and
    # dropped the whole parse to `None`.
    match = re.search(rb"encoding\s*=\s*[\"']([A-Za-z0-9_.\-]+)[\"']", data[:200])
    if match:
        try:
            return data.decode(match.group(1).decode("ascii"))
        except (LookupError, UnicodeDecodeError):
            return None
    return None


def safe_unzip(data: bytes) -> io.BytesIO:
    """Validate a ZIP-backed office file's decompression, then hand back a stream.

    ODF and OOXML are ZIP+XML, and a small upload can decompress to a huge amount of
    memory. Every member is read through a bounded stream — never trusting the
    forgeable `ZipInfo.file_size` in the central directory — and the member count and
    running total are capped. Returns a fresh stream over the *validated* bytes for
    the parser to open; raises `ValueError` when a bound is exceeded, which each
    parser turns into a caught `None`.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        if len(names) > settings.CHAT_ARCHIVE_MAX_MEMBERS:
            raise ValueError("archive has too many members")
        total = 0
        for name in names:
            member_total = 0
            with archive.open(name) as member:
                while chunk := member.read(_ARCHIVE_CHUNK):
                    member_total += len(chunk)
                    if member_total > settings.CHAT_ARCHIVE_MEMBER_MAX_BYTES:
                        raise ValueError("archive member too large")
                    total += len(chunk)
                    if total > settings.CHAT_ARCHIVE_TOTAL_MAX_BYTES:
                        raise ValueError("archive too large")
    return io.BytesIO(data)


def _clamp_odf_space_runs(document: Any, budget: int) -> None:
    """Clamp every `<text:s text:c=N>` repeat so a walk cannot allocate a bomb.

    odfpy's own `extractText` expands `<text:s>` to `" " * int(text:c)` before any
    character cap is applied, so a sub-kilobyte ODF declaring `text:c="10000000000"`
    allocates gigabytes of spaces inside the extraction — a post-decompression bomb
    `safe_unzip` cannot see, because the XML member itself is tiny (#1591, §7 finding
    3). The count is attacker-controlled, so each run is clamped in place to what is
    left of `budget` before extraction; the bound is the parsed-text cap, far above
    any real run of spaces, and the cell/paragraph budgets narrow it further.
    """
    from odf.text import S

    remaining = budget
    for element in document.getElementsByType(S):
        count = int(element.getAttribute("c") or 1)
        clamped = max(0, min(count, remaining))
        element.setAttribute("c", str(clamped))
        remaining -= clamped


@dataclass(frozen=True)
class TiffConversion:
    """The PNGs a TIFF contributes to a turn, and what was left out."""

    images: list[bytes]
    """One PNG per shown page, metadata stripped, each within the per-page cap."""

    total: int | None
    """The page count when it is *safely* known — the sequence was exhausted without
    hitting the page cap. `None` when the bounded walk stopped early, so the count
    was never established without traversing the whole attacker-controlled IFD chain."""

    omitted: bool
    """Whether any page was left out — the page cap was reached, or a page could not
    be decoded or reduced below the per-page byte cap."""


def tiff_pages_to_png(
    data: bytes, *, max_pages: int, max_bytes: int, max_pixels: int
) -> TiffConversion:
    """Convert a TIFF's pages to PNG for the model, bomb-guarded and metadata-free.

    TIFF is not accepted by the vision APIs, so it is converted to PNG at the point
    it is shown. Multi-page scans contribute more than page one, up to `max_pages`.

    The guards do not trust attacker-controlled counts and do not mutate any
    process-global Pillow state (the file pool is shared): each frame's declared
    `size` is checked against `max_pixels` *before* it is decoded, the sequence is
    stopped one frame past the cap rather than reading a total that walks the whole
    IFD chain, and any decode error is a caught failure (#1591, §7 finding 5).
    """
    from PIL import Image, ImageSequence

    images: list[bytes] = []
    omitted = False
    total: int | None = None
    try:
        img_ctx = Image.open(io.BytesIO(data))
    except Exception as exc:  # Not a TIFF, or a header too broken to open at all.
        logger.warning("TIFF conversion failed: %s", exc)
        return TiffConversion(images=[], total=None, omitted=False)
    with img_ctx as img:
        frames = ImageSequence.Iterator(img)
        seen = 0
        while True:
            try:
                frame = next(frames)
            except StopIteration:
                # Exhausted without breaking, so every frame was counted and the
                # total is safe to state — no extra IFD walk needed.
                total = seen
                break
            except Exception as exc:
                # A broken IFD partway down the chain: keep the pages already
                # converted rather than discarding a usable page one, and mark the
                # rest omitted (#1591, third-pass finding 4).
                logger.warning("TIFF frame walk stopped early: %s", exc)
                omitted = True
                break
            # Capped on frames *examined*, not on images produced: a frame
            # rejected for its pixel count or output size does not grow `images`,
            # so gating on that count alone let a long chain of oversized/malformed
            # frames walk the whole attacker-controlled IFD chain despite the page
            # cap (#1591, §7 finding 2). The cap is checked *after* the pull so
            # this one frame past `max_pages` proves more pages exist, rather than
            # claiming omission at the exact limit — a one-page TIFF with a cap of
            # one is exhausted here, not truncated (#1591, §7 finding 5).
            if seen >= max_pages:
                omitted = True
                break
            seen += 1
            try:
                png = _frame_to_png(frame, max_bytes=max_bytes, max_pixels=max_pixels)
            except Exception as exc:  # One unreadable frame does not sink the others.
                logger.warning("TIFF frame decode failed: %s", exc)
                omitted = True
                continue
            if png is None:
                omitted = True
                continue
            images.append(png)
    return TiffConversion(images=images, total=total, omitted=omitted)


def _frame_to_png(frame: Any, *, max_bytes: int, max_pixels: int) -> bytes | None:
    """One TIFF frame as PNG bytes, or `None` if it is a bomb or cannot be shrunk."""
    width, height = frame.size
    if width * height > max_pixels:
        return None
    image = frame.convert("RGB")
    for divisor in (1, 2, 4, 8):
        candidate = image if divisor == 1 else image.reduce(divisor)
        buffer = io.BytesIO()
        candidate.save(buffer, format="PNG")
        if buffer.tell() <= max_bytes:
            return buffer.getvalue()
    return None


class FileUploadService:
    """Service for file upload validation, parsing, and persistence."""

    ALLOWED_MIME_TYPES = ALLOWED_MIME_TYPES

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def validate_upload(
        content_type: str | None, size: int, filename: str = ""
    ) -> tuple[bool, str | None]:
        """Validate a chat attachment's type and size before it is stored.

        The metadata phase, callable before the bytes exist (the channel preflight
        runs it pre-download). Acceptance is `(normalised MIME ∈ allowlist) OR
        (extension ∈ allowed set)`, because browsers send `application/octet-stream`
        for `.msg`, `.odt`, `.xls` and often `.doc`. A *specific* declared MIME that
        contradicts the extension is refused; the byte phase (`validate_bytes`) then
        checks the content once it has arrived.

        The size ceiling is `CHAT_MAX_UPLOAD_SIZE_MB`, its own setting rather than
        the knowledge base's, because an attachment to an agent with no workspace is
        pasted whole into the prompt while a document is chunked — the two surfaces
        fail differently at the same size (#498).

        Returns:
            Tuple of (is_valid, error_message).
        """
        normalized = normalize_media_type(content_type)
        accepted = (
            normalized in ALLOWED_MIME_TYPES or file_extension(filename) in ALLOWED_EXTENSIONS
        )
        if not accepted:
            return False, f"File type '{content_type}' is not supported."
        if has_format_conflict(content_type, filename):
            return False, "The file's declared type does not match its extension."
        limit_mb = settings.CHAT_MAX_UPLOAD_SIZE_MB
        if size > limit_mb * 1024 * 1024:
            return False, f"File too large. Maximum size is {limit_mb}MB."
        return True, None

    @staticmethod
    def validate_bytes(
        data: bytes, content_type: str | None, filename: str = ""
    ) -> tuple[bool, str | None]:
        """Validate a chat attachment against its own first bytes, once they exist.

        The byte phase: for a format whose container is knowable cheaply — TIFF, the
        OLE-backed legacy formats, the ZIP-backed OOXML/OpenDocument ones — the magic
        bytes must match the resolved format. This catches a forged signature and a
        MIME/extension conflict that only the content reveals, on a file that already
        cleared `validate_upload`. Formats with no cheap signature (PDF, the text
        family, the web-safe images) are not sniffed here.
        """
        container = expected_container(content_type, filename)
        if container is None:
            return True, None
        if sniff_container(data) != container:
            return (
                False,
                "This file could not be accepted — its contents do not match its "
                "type or extension.",
            )
        return True, None

    @staticmethod
    def classify_file(mime_type: str, filename: str) -> str:
        """Classify file type based on MIME type and extension."""
        return classify_file(mime_type, filename)

    async def parse_content(
        self,
        data: bytes,
        file_type: str,
        mime_type: str = "",
        filename: str = "",
    ) -> str | None:
        """Parse file content into text, dispatched by the canonical format.

        Returns extracted text (bounded by `CHAT_PARSED_TEXT_MAX_CHARS`) or `None`
        when parsing fails or the type carries no text (an image).

        Every in-process branch is blocking CPU work — pymupdf over every page,
        openpyxl over every cell, odfpy/python-pptx over a decompressed archive — with
        no suspension point, so it runs on the dedicated file pool rather than the
        request loop (#1108). DOC is the exception: it is an `await` on a managed
        `soffice` subprocess (`office_convert.py`), already off the loop and bounded
        by its own semaphore.
        """
        text = await self._parse_by_format(data, file_type, resolve_format(mime_type, filename))
        return cap_text(text, settings.CHAT_PARSED_TEXT_MAX_CHARS)

    async def _parse_by_format(self, data: bytes, file_type: str, fmt: str) -> str | None:
        if file_type == "text":
            return await run_blocking(self._parse_text_content, data)
        if file_type == "pdf":
            return await run_blocking(self._parse_pdf_content, data)
        if file_type == "docx":
            return await run_blocking(self._parse_docx_content, data)
        if file_type == "spreadsheet":
            if fmt == "xls":
                return await run_blocking(self._parse_xls_content, data)
            if fmt == "ods":
                return await run_blocking(self._parse_ods_content, data)
            return await run_blocking(self._parse_spreadsheet_content, data)
        if file_type == "document":
            if fmt == "doc":
                return await self._parse_doc_content(data)
            return await run_blocking(self._parse_odt_content, data)
        if file_type == "presentation":
            if fmt == "odp":
                return await run_blocking(self._parse_odp_content, data)
            return await run_blocking(self._parse_pptx_content, data)
        if file_type == "email":
            return await run_blocking(self._parse_msg_content, data)
        return None

    @staticmethod
    def _parse_text_content(data: bytes) -> str | None:
        """Extract text from text-based files.

        UTF-8 first, then a BOM/`encoding=`-declaration fallback: a UTF-16 or UTF-32
        XML document (common for exported XML) would fail an unconditional UTF-8
        decode, so its declared encoding is honoured rather than assumed (#1591,
        §7 #9).
        """
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return _decode_declared(data)

    @staticmethod
    def _parse_pdf_pymupdf(data: bytes) -> str | None:
        """Extract text from PDF using PyMuPDF."""
        try:
            import pymupdf

            doc: Any = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
            text_parts = []
            for page in doc:
                text = page.get_text("text")
                if text.strip():
                    text_parts.append(text.strip())
            doc.close()
            return "\n\n".join(text_parts) if text_parts else None
        except Exception as e:
            logger.warning("PyMuPDF PDF parsing failed: %s", e)
            return None

    def _parse_pdf_content(self, data: bytes) -> str | None:
        """Read a PDF attached to a chat message.

        PyMuPDF, and only PyMuPDF. A chat attachment belongs to no collection,
        so there is no stored configuration to read a parser choice from, and
        the two alternatives were worse than nothing here: LlamaParse bills per
        page and needs a key, LiteParse needs a heavier local toolchain, and
        both were wrapped in `except Exception: return self._parse_pdf_pymupdf()`
        - which meant this file had been silently using PyMuPDF all along. The
        LiteParse branch could not have worked at all: it called a `parse_async`
        method the binding does not define.
        """
        return self._parse_pdf_pymupdf(data)

    @staticmethod
    def _parse_docx_content(data: bytes) -> str | None:
        """Extract text from DOCX."""
        try:
            from docx import Document as DOCXDocument

            # Through `safe_unzip` like the other ZIP-backed formats: a DOCX is a
            # ZIP of XML, so a small upload can decompress to a huge amount of
            # memory. `python-docx` opening the raw bytes would skip the member,
            # total-size and member-count guards the ODF/PPTX parsers already apply
            # (#1591, §7 finding 1).
            doc: Any = DOCXDocument(safe_unzip(data))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            logger.warning("DOCX parsing failed: %s", e)
            return None

    @staticmethod
    def _parse_spreadsheet_content(data: bytes) -> str | None:
        """Extract a workbook as tab-separated rows, one block per sheet.

        Every sheet, named. A workbook's second sheet is where the data usually
        is - the first is a cover or an index - and a reader that took only the
        active one would answer questions about a file it had half read.

        Tabs rather than commas: a cell holding "1,5" is a number in half of
        Europe, and comma-separating those rows produces a table with a column
        that appears and disappears down the page. `read_only` because a workbook
        is opened here to be read once and thrown away, and it is what keeps a
        large one from being materialised in full.

        Trailing empty cells and empty rows are dropped. A sheet whose used range
        is wider than its data - which is most of them, after a column has been
        cleared - otherwise contributes rows of tabs, and those cost tokens to say
        nothing.
        """
        try:
            from openpyxl import load_workbook

            # Through `safe_unzip`, the same guard the ODF/PPTX parsers use: an XLSX
            # is a ZIP of XML and `read_only=True` bounds the cells materialised, not
            # the decompression of shared strings or workbook metadata, so a small
            # upload could still expand without limit (#1591, §7 finding 1).
            workbook: Any = load_workbook(safe_unzip(data), read_only=True, data_only=True)
            try:
                blocks: list[str] = []
                for sheet in workbook.worksheets:
                    rows: list[str] = []
                    for row in sheet.iter_rows(values_only=True):
                        cells = ["" if value is None else str(value) for value in row]
                        while cells and cells[-1] == "":
                            cells.pop()
                        if cells:
                            rows.append("\t".join(cells))
                    if rows:
                        blocks.append(f"Sheet: {sheet.title}\n" + "\n".join(rows))
                return "\n\n".join(blocks) or None
            finally:
                # `read_only` keeps file handles open until it is closed, and this
                # runs inside a request.
                workbook.close()
        except Exception as e:
            logger.warning("Spreadsheet parsing failed: %s", e)
            return None

    @staticmethod
    def _parse_xls_content(data: bytes) -> str | None:
        """Extract a legacy `.xls` workbook, mirroring the openpyxl output shape.

        `xlrd` reads the old BIFF format openpyxl cannot. Dates arrive as serial
        numbers and are rendered back to ISO; a password-protected or otherwise
        unreadable workbook raises and becomes a caught `None` (#1591, §5 #10).
        """
        try:
            import xlrd

            # `ragged_rows=True` so a sparse sheet whose used range is 65_536x256 for
            # one value is not padded to that full rectangle in memory on open, and a
            # cell budget so the read loop cannot sweep it either (#1591).
            book: Any = xlrd.open_workbook(
                file_contents=data, formatting_info=False, ragged_rows=True
            )
            blocks: list[str] = []
            budget = _XLS_MAX_CELLS
            for sheet in book.sheets():
                rows: list[str] = []
                for r in range(sheet.nrows):
                    width = sheet.row_len(r)
                    cells = [_xls_cell(book, sheet.cell(r, c)) for c in range(width)]
                    budget -= width
                    while cells and cells[-1] == "":
                        cells.pop()
                    if cells:
                        rows.append("\t".join(cells))
                    if budget <= 0:
                        break
                if rows:
                    blocks.append(f"Sheet: {sheet.name}\n" + "\n".join(rows))
                if budget <= 0:
                    break
            return "\n\n".join(blocks) or None
        except Exception as e:
            logger.warning("XLS parsing failed: %s", e)
            return None

    @staticmethod
    def _parse_ods_content(data: bytes) -> str | None:
        """Extract an OpenDocument spreadsheet as tab-separated sheets."""
        try:
            from odf.opendocument import load
            from odf.table import Table, TableCell, TableRow
            from odf.teletype import extractText

            document: Any = load(safe_unzip(data))
            # `extractText` below expands `<text:s>` before any cap, so the space
            # runs are clamped in the DOM first (#1591, §7 finding 3).
            _clamp_odf_space_runs(document, settings.CHAT_PARSED_TEXT_MAX_CHARS)
            blocks: list[str] = []
            budget = _ODS_MAX_CELLS
            char_budget = settings.CHAT_PARSED_TEXT_MAX_CHARS
            for table in document.getElementsByType(Table):
                name = table.getAttribute("name") or "Sheet"
                rows: list[str] = []
                for row in table.getElementsByType(TableRow):
                    cells: list[str] = []
                    for cell in row.getElementsByType(TableCell):
                        text = extractText(cell)
                        # Clamped to *both* budgets: the repeat count is
                        # attacker-controlled, so an unclamped `[text] * repeat`
                        # allocates an unbounded list (the cell budget), and the later
                        # `"\t".join(cells)` then materialises the value once per
                        # reference - a single 10 KB cell repeated a million times is a
                        # ~10 GB string built before `cap_text` is reached, which the
                        # cell budget alone does not stop (the character budget)
                        # (#1591, §7 finding 3).
                        repeat = max(
                            1, min(int(cell.getAttribute("numbercolumnsrepeated") or 1), budget)
                        )
                        if text:
                            repeat = min(repeat, max(1, char_budget // len(text)))
                        cells.extend([text] * repeat)
                        budget -= repeat
                        char_budget -= repeat * len(text)
                        if budget <= 0 or char_budget <= 0:
                            break
                    while cells and cells[-1] == "":
                        cells.pop()
                    if cells:
                        line = "\t".join(cells)
                        rows.append(line)
                        # A nonempty row may repeat via `table:number-rows-repeated`;
                        # emitting the DOM row once would silently drop the copies and
                        # hand the model wrong counts. Each extra copy is charged to
                        # both budgets so an attacker-chosen count cannot outrun the
                        # bound the columns already answer to (#1591). Trailing empty
                        # rows carry huge repeats too, but their cells pop to nothing
                        # above, so only real data expands here.
                        row_repeat = max(1, int(row.getAttribute("numberrowsrepeated") or 1))
                        for _ in range(row_repeat - 1):
                            if budget <= 0 or char_budget <= 0:
                                break
                            rows.append(line)
                            budget -= len(cells)
                            char_budget -= len(line)
                    if budget <= 0 or char_budget <= 0:
                        break
                if rows:
                    blocks.append(f"Sheet: {name}\n" + "\n".join(rows))
                if budget <= 0 or char_budget <= 0:
                    break
            return "\n\n".join(blocks) or None
        except Exception as e:
            logger.warning("ODS parsing failed: %s", e)
            return None

    @staticmethod
    def _parse_odt_content(data: bytes) -> str | None:
        """Extract the paragraphs of an OpenDocument text document."""
        try:
            from odf.opendocument import load
            from odf.teletype import extractText
            from odf.text import P

            document: Any = load(safe_unzip(data))
            # `extractText` expands `<text:s>` before any cap; clamp first (#1591).
            _clamp_odf_space_runs(document, settings.CHAT_PARSED_TEXT_MAX_CHARS)
            lines = [extractText(p) for p in document.getElementsByType(P)]
            return "\n".join(line for line in lines if line.strip()) or None
        except Exception as e:
            logger.warning("ODT parsing failed: %s", e)
            return None

    @staticmethod
    def _parse_odp_content(data: bytes) -> str | None:
        """Extract the text frames of an OpenDocument presentation."""
        try:
            from odf.opendocument import load
            from odf.teletype import extractText
            from odf.text import P

            document: Any = load(safe_unzip(data))
            # `extractText` expands `<text:s>` before any cap; clamp first (#1591).
            _clamp_odf_space_runs(document, settings.CHAT_PARSED_TEXT_MAX_CHARS)
            lines = [extractText(p) for p in document.getElementsByType(P)]
            return "\n".join(line for line in lines if line.strip()) or None
        except Exception as e:
            logger.warning("ODP parsing failed: %s", e)
            return None

    @staticmethod
    def _parse_pptx_content(data: bytes) -> str | None:
        """Extract a PPTX: shape text, table cells and slide notes, per slide."""
        try:
            from pptx import Presentation

            presentation: Any = Presentation(safe_unzip(data))
            slides: list[str] = []
            for index, slide in enumerate(presentation.slides, start=1):
                lines: list[str] = []
                for shape in slide.shapes:
                    if shape.has_text_frame and shape.text_frame.text.strip():
                        lines.append(shape.text_frame.text)
                    if shape.has_table:
                        for row in shape.table.rows:
                            lines.append("\t".join(cell.text for cell in row.cells))
                if slide.has_notes_slide:
                    notes = slide.notes_slide.notes_text_frame.text
                    if notes.strip():
                        lines.append(f"Notes: {notes}")
                if lines:
                    slides.append(f"Slide {index}\n" + "\n".join(lines))
            return "\n\n".join(slides) or None
        except Exception as e:
            logger.warning("PPTX parsing failed: %s", e)
            return None

    @staticmethod
    def _parse_msg_content(data: bytes) -> str | None:
        """Extract an Outlook `.msg` (OLE) with olefile, reading the MAPI streams.

        BSD-licensed `olefile` rather than GPL `extract-msg`: the headers and the
        plain body are read straight from the MAPI property streams, falling back to
        the tag-stripped HTML body. Embedded attachments are *listed by name*, never
        recursed — a `.msg` can nest `.msg`s, a zip-bomb-shaped risk this declines
        (#1591, §5 #1/#10).
        """
        try:
            import olefile

            if not olefile.isOleFile(io.BytesIO(data)):
                return None
            ole: Any = olefile.OleFileIO(io.BytesIO(data))
            try:
                return _msg_text(ole)
            finally:
                ole.close()
        except Exception as e:
            logger.warning("MSG parsing failed: %s", e)
            return None

    async def _parse_doc_content(self, data: bytes) -> str | None:
        """Extract a legacy `.doc` by converting it through managed LibreOffice.

        The one format with no viable pure-Python reader. Absent `soffice` (a
        non-Docker dev box) this returns `None` and the model is told the text could
        not be extracted — the same graceful degradation RAG documents.
        """
        try:
            return await libreoffice_convert(
                data, suffix=".doc", timeout=settings.CHAT_CONVERT_TIMEOUT_SECONDS
            )
        except Exception as e:
            logger.warning("DOC parsing failed: %s", e)
            return None

    async def upload(
        self,
        *,
        user_id: Any,
        file_data: bytes,
        filename: str,
        content_type: str | None,
    ) -> ChatFile:
        """Validate, parse, persist, and record a chat file upload.

        Raises:
            BadRequestError: If the file's type/size or its content is invalid.
        """
        is_valid, error = self.validate_upload(content_type, len(file_data), filename)
        if not is_valid:
            raise BadRequestError(message=error or "Invalid file")
        is_valid, error = self.validate_bytes(file_data, content_type, filename)
        if not is_valid:
            raise BadRequestError(message=error or "Invalid file")

        # The *resolved* MIME is stored, not the caller-declared header: an
        # `application/octet-stream` `.tiff` becomes `image/tiff`, so the download
        # route and the inline-conversion path read one trustworthy field (#1591).
        resolved_mime = canonical_mime(content_type, filename)
        file_type = self.classify_file(resolved_mime, filename)
        parsed_content = await self.parse_content(file_data, file_type, resolved_mime, filename)

        storage = get_file_storage()
        storage_path = await storage.save(str(user_id), filename, file_data)

        return await self.create_chat_file(
            user_id=user_id,
            filename=filename,
            mime_type=resolved_mime,
            size=len(file_data),
            storage_path=storage_path,
            file_type=file_type,
            parsed_content=parsed_content,
        )

    async def discard(self, chat_file: ChatFile) -> None:
        """Delete a stored file and the row recording it - the inverse of `upload`.

        For a caller whose turn was refused after the bytes were already stored.
        The bytes go first: a row deleted while the file survives leaves nothing
        pointing at it.
        """
        await get_file_storage().delete(chat_file.storage_path)
        await chat_file_repo.delete(self.db, db_file=chat_file)

    def get_file_path(self, storage_path: str) -> str | None:
        """Resolve a storage path to an absolute filesystem path."""
        full_path = get_file_storage().get_full_path(storage_path)
        return str(full_path) if full_path is not None else None

    async def get_user_file(self, file_id: Any, user_id: Any) -> ChatFile:
        """Get a file by ID, verifying ownership.

        Raises:
            NotFoundError: If file does not exist or user has no access.
        """
        chat_file = await chat_file_repo.get_by_id(self.db, file_id)
        if not chat_file or str(chat_file.user_id) != str(user_id):
            raise NotFoundError(message="File not found")
        return chat_file

    async def create_chat_file(
        self,
        *,
        user_id: Any,
        filename: str,
        mime_type: str,
        size: int,
        storage_path: str,
        file_type: str,
        parsed_content: str | None = None,
    ) -> ChatFile:
        """Create a chat file record in the database."""
        return await chat_file_repo.create(
            self.db,
            user_id=user_id,
            filename=filename,
            mime_type=mime_type,
            size=size,
            storage_path=storage_path,
            file_type=file_type,
            parsed_content=parsed_content,
        )


def _xls_cell(book: Any, cell: Any) -> str:
    """One `.xls` cell as text, mirroring the openpyxl output for consistency."""
    import xlrd

    if cell.ctype == xlrd.XL_CELL_EMPTY or cell.ctype == xlrd.XL_CELL_BLANK:
        return ""
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return "TRUE" if cell.value else "FALSE"
    if cell.ctype == xlrd.XL_CELL_DATE:
        stamp = xlrd.xldate.xldate_as_datetime(cell.value, book.datemode)
        if (stamp.hour, stamp.minute, stamp.second) == (0, 0, 0):
            return stamp.date().isoformat()
        return stamp.isoformat()
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        number = cell.value
        return str(int(number)) if number == int(number) else str(number)
    return str(cell.value)


def _msg_decode(raw: bytes, encoding: str) -> str:
    """Decode a MAPI string stream, dropping the NUL that PostgreSQL rejects.

    `PtypString` streams are NUL-terminated, and `str.strip()` does not remove
    `\\x00`, so a real subject, body, recipient or attachment name would carry the
    terminator into the `Text` column — which PostgreSQL refuses, failing the upload
    after its bytes were already stored. Stripped at every property read, the same
    way `_sanitize_filename` drops it from a name (#1591).
    """
    return raw.decode(encoding, errors="replace").replace("\x00", "").strip()


def _msg_stream(ole: Any, prop: str) -> str | None:
    """A MAPI string property, preferring the Unicode (`001F`) over the ANSI (`001E`)."""
    for suffix, encoding in (("001F", "utf-16-le"), ("001E", "cp1252")):
        name = f"__substg1.0_{prop}{suffix}"
        if ole.exists(name):
            return _msg_decode(ole.openstream(name).read(), encoding)
    return None


_TAG_RE = re.compile(r"<[^>]+>")


def _msg_html_body(ole: Any) -> str | None:
    """The HTML body stream, stripped of tags — the fallback when there is no plain body."""
    name = "__substg1.0_10130102"
    if not ole.exists(name):
        return None
    raw = ole.openstream(name).read()
    # A NUL survives `text.split()` (it is not whitespace) and would reach the `Text`
    # column PostgreSQL refuses, so it is dropped before the tags are stripped (#1591).
    html = raw.decode("utf-8", errors="replace").replace("\x00", " ")
    text = _TAG_RE.sub(" ", html)
    return " ".join(text.split()) or None


def _msg_recipients(ole: Any) -> list[str]:
    """The recipients, normalised to `Name <addr>` from the `__recip` storages."""
    storages = sorted(
        {entry[0] for entry in ole.listdir() if entry[0].startswith("__recip_version1.0_")}
    )
    people: list[str] = []
    for storage in storages:
        display = _msg_sub(ole, storage, "3001")
        email = _msg_sub(ole, storage, "39FE") or _msg_sub(ole, storage, "3003")
        if display and email:
            people.append(f"{display} <{email}>")
        elif display or email:
            people.append(display or email or "")
    return people


def _msg_sub(ole: Any, storage: str, prop: str) -> str | None:
    for suffix, encoding in (("001F", "utf-16-le"), ("001E", "cp1252")):
        name = f"{storage}/__substg1.0_{prop}{suffix}"
        if ole.exists(name):
            return _msg_decode(ole.openstream(name).read(), encoding)
    return None


def _msg_attachments(ole: Any) -> list[str]:
    """The names of embedded attachments — listed, never recursed."""
    storages = sorted(
        {entry[0] for entry in ole.listdir() if entry[0].startswith("__attach_version1.0_")}
    )
    names: list[str] = []
    for storage in storages:
        name = _msg_sub(ole, storage, "3707") or _msg_sub(ole, storage, "3704")
        if name:
            names.append(name)
    return names


def _msg_text(ole: Any) -> str | None:
    """Assemble the readable text of an Outlook message from its MAPI streams."""
    subject = _msg_stream(ole, "0037")
    sender = _msg_stream(ole, "0C1A") or _msg_stream(ole, "0C1F")
    body = _msg_stream(ole, "1000") or _msg_html_body(ole)
    recipients = _msg_recipients(ole)
    attachments = _msg_attachments(ole)

    parts: list[str] = []
    if sender:
        parts.append(f"From: {sender}")
    if recipients:
        parts.append(f"To: {', '.join(recipients)}")
    if subject:
        parts.append(f"Subject: {subject}")
    header = "\n".join(parts)
    sections = [section for section in (header, body) if section]
    if attachments:
        sections.append(f"Attachments: {', '.join(attachments)}")
    return "\n\n".join(sections) or None
