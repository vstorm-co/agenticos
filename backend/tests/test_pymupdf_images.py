"""Repeated PDF images must cost one extraction, not one per reference (#2584)."""

import asyncio
import random
from pathlib import Path
from unittest.mock import patch

import pymupdf
import pytest

from app.db.vector_tables import VectorScope
from app.services.rag.config import RAGSettings
from app.services.rag.documents import DocumentProcessor, PyMuPDFParser
from app.services.rag.image_describer import BaseImageDescriber
from app.services.rag.models import Document, DocumentImage, DocumentMetadata, DocumentPageChunk
from app.services.rag.vectorstore import PgVectorStore

pytestmark = pytest.mark.anyio
DEPLOYMENT_WIDE = VectorScope(tenant=None)


class RecordingDescriber(BaseImageDescriber):
    def __init__(self, description: str = "A shared diagram.") -> None:
        self.description = description
        self.calls: list[tuple[bytes, str]] = []

    async def describe(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        self.calls.append((image_bytes, mime_type))
        return self.description


@pytest.fixture
def illustrated_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "manual.pdf"
    pixels = random.Random(42).randbytes(48 * 48 * 3)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, 48, 48, pixels, False)
    with pymupdf.open() as doc:
        xref = 0
        for index in range(3):
            page = doc.new_page()
            page.insert_text((72, 250), f"Page {index + 1}: " + "Useful manual text. " * 20)
            for offset in (0, 100):
                xref = page.insert_image(
                    pymupdf.Rect(72 + offset, 72, 120 + offset, 120),
                    stream=pixmap.tobytes("png") if not xref else None,
                    xref=xref,
                )
        doc.save(path)
    return path


async def test_text_only_ingestion_never_reads_embedded_images(illustrated_pdf: Path) -> None:
    with (
        patch.object(pymupdf.Page, "get_images", autospec=True) as enumerate_images,
        patch.object(pymupdf.Document, "extract_image", autospec=True) as extract,
    ):
        document = await DocumentProcessor(RAGSettings()).process_file(illustrated_pdf)

    enumerate_images.assert_not_called()
    extract.assert_not_called()
    assert len(document.pages) == 3
    assert all("Useful manual text." in page.content for page in document.pages)
    assert all(not page.images for page in document.pages)
    assert document.chunked_pages


async def test_repeated_images_share_bytes_but_keep_each_pages_description(
    illustrated_pdf: Path,
) -> None:
    describer = RecordingDescriber()
    original = pymupdf.Document.extract_image
    with patch.object(
        pymupdf.Document, "extract_image", autospec=True, side_effect=original
    ) as extract:
        document = await DocumentProcessor(RAGSettings(), describer).process_file(illustrated_pdf)

    assert extract.call_count == 1
    assert len(describer.calls) == 1
    assert [len(page.images) for page in document.pages] == [1, 1, 1]
    images = [page.images[0] for page in document.pages]
    assert [image.page_num for image in images] == [1, 2, 3]
    assert all(image.image_bytes is images[0].image_bytes for image in images)
    assert all(page.content.count("[Image: A shared diagram.]") == 1 for page in document.pages)
    assert document.chunked_pages
    assert any(
        "[Image: A shared diagram.]" in chunk.chunk_content for chunk in document.chunked_pages
    )


async def test_chunks_do_not_carry_copies_of_page_images(illustrated_pdf: Path) -> None:
    processor = DocumentProcessor(
        RAGSettings(chunk_size=100, chunk_overlap=0), RecordingDescriber()
    )
    document = await processor.process_file(illustrated_pdf)

    assert document.chunked_pages
    assert len(document.chunked_pages) > len(document.pages)
    assert all(not chunk.images for chunk in document.chunked_pages)
    for chunk in document.chunked_pages:
        page = document.pages[chunk.page_num - 1]
        assert chunk.page_id == page.page_id
        assert chunk.parent_doc_id == document.id
        assert chunk.content == page.content


async def test_payload_free_chunks_preserve_image_metadata(illustrated_pdf: Path) -> None:
    document = await DocumentProcessor(
        RAGSettings(chunk_size=100, chunk_overlap=0), RecordingDescriber()
    ).process_file(illustrated_pdf)
    assert document.chunked_pages
    store = PgVectorStore.__new__(PgVectorStore)
    for chunk in document.chunked_pages:
        assert not chunk.images
        metadata = store._build_chunk_metadata(chunk, document, DEPLOYMENT_WIDE)
        assert metadata["has_images"] is True
        assert metadata["image_count"] == 1


@pytest.mark.parametrize("with_image", [False, True])
def test_legacy_inline_images_still_supply_chunk_metadata(with_image: bool) -> None:
    chunk = DocumentPageChunk(
        page_num=1,
        content="text",
        chunk_content="text",
        images=[DocumentImage(image_bytes=b"image")] if with_image else [],
    )
    document = Document(
        pages=[chunk], metadata=DocumentMetadata(filename="manual.pdf", filesize=1, filetype="pdf")
    )
    metadata = PgVectorStore.__new__(PgVectorStore)._build_chunk_metadata(
        chunk, document, DEPLOYMENT_WIDE
    )
    assert metadata["has_images"] is with_image
    assert metadata["image_count"] == int(with_image)


async def test_image_cache_is_scoped_to_one_parse(illustrated_pdf: Path) -> None:
    parser = PyMuPDFParser(image_describer=RecordingDescriber())
    original = pymupdf.Document.extract_image
    with patch.object(
        pymupdf.Document, "extract_image", autospec=True, side_effect=original
    ) as extract:
        first = await parser.parse(illustrated_pdf)
        second = await parser.parse(illustrated_pdf)

    assert extract.call_count == 2
    assert first.pages[0].images[0].image_id != second.pages[0].images[0].image_id


@pytest.mark.parametrize("result", [None, {"image": b"tiny", "ext": "png"}])
async def test_unusable_images_are_not_extracted_again(
    illustrated_pdf: Path, result: object
) -> None:
    with patch.object(
        pymupdf.Document, "extract_image", autospec=True, return_value=result
    ) as extract:
        document = await PyMuPDFParser(image_describer=RecordingDescriber()).parse(illustrated_pdf)

    assert extract.call_count == 1
    assert all(not page.images for page in document.pages)


async def test_unreadable_images_are_logged_once_and_do_not_fail_text(
    illustrated_pdf: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with patch.object(
        pymupdf.Document, "extract_image", autospec=True, side_effect=ValueError("broken")
    ) as extract:
        document = await PyMuPDFParser(image_describer=RecordingDescriber()).parse(illustrated_pdf)

    assert extract.call_count == 1
    assert all(not page.images for page in document.pages)
    assert all("Useful manual text." in page.content for page in document.pages)
    assert caplog.text.count("Skipping an unreadable image") == 1


async def test_an_empty_description_is_cached_too(illustrated_pdf: Path) -> None:
    describer = RecordingDescriber("")
    document = await DocumentProcessor(RAGSettings(), describer).process_file(illustrated_pdf)

    assert len(describer.calls) == 1
    assert all("[Image:" not in page.content for page in document.pages)


async def test_distinct_images_are_still_extracted_and_described(illustrated_pdf: Path) -> None:
    path = illustrated_pdf.with_name("two-images.pdf")
    pixels = random.Random(99).randbytes(48 * 48 * 3)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, 48, 48, pixels, False)
    with pymupdf.open(illustrated_pdf) as doc:
        doc[1].insert_image(pymupdf.Rect(250, 72, 298, 120), stream=pixmap.tobytes("png"))
        doc.save(path)
    describer = RecordingDescriber()
    original = pymupdf.Document.extract_image
    with patch.object(
        pymupdf.Document, "extract_image", autospec=True, side_effect=original
    ) as extract:
        document = await DocumentProcessor(RAGSettings(), describer).process_file(path)

    assert extract.call_count == 2
    assert len(describer.calls) == 2
    assert describer.calls[0][0] != describer.calls[1][0]
    assert [len(page.images) for page in document.pages] == [1, 2, 1]
    assert document.chunked_pages
    store = PgVectorStore.__new__(PgVectorStore)
    for chunk in document.chunked_pages:
        metadata = store._build_chunk_metadata(chunk, document, DEPLOYMENT_WIDE)
        assert metadata["image_count"] == [1, 2, 1][chunk.page_num - 1]


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_pdf_is_closed_when_parsing_fails_or_is_cancelled(
    illustrated_pdf: Path, failure: type[BaseException]
) -> None:
    doc = pymupdf.open(illustrated_pdf)
    parser = PyMuPDFParser()
    with (
        patch("pymupdf.open", return_value=doc),
        patch.object(parser, "_extract_text", side_effect=failure),
        pytest.raises(failure),
    ):
        await parser.parse(illustrated_pdf)

    assert doc.is_closed
