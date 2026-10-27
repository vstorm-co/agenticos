"""A citation names a page only where the source has pages (#2489)."""

import pytest

from app.services.rag.citation import PAGED_FORMATS, citation_locator, cited_page


class TestCitedPage:
    def test_a_pdf_keeps_its_page(self):
        assert cited_page({"filetype": "pdf", "page_num": 7}) == 7

    def test_the_format_is_read_case_blind(self):
        """`filetype` keeps the upload's case for display: `Report.PDF` is still a PDF."""
        assert cited_page({"filetype": "PDF", "page_num": 2}) == 2

    @pytest.mark.parametrize("filetype", ["md", "txt", "docx", "html", "xlsx", "csv", "png"])
    def test_a_stored_page_1_on_an_unpaged_format_is_not_a_page(self, filetype):
        """Chunks ingested before the fix carry `page_num` 1; they cite without it."""
        assert cited_page({"filetype": filetype, "page_num": 1}) is None

    def test_a_presentation_keeps_its_slide(self):
        assert cited_page({"filetype": "pptx", "page_num": 4}) == 4

    def test_the_filename_answers_when_no_filetype_was_stored(self):
        assert cited_page({"filename": "policy.pdf", "page_num": 3}) == 3
        assert cited_page({"filename": "capabilities.pl.md", "page_num": 1}) is None

    def test_the_stored_filetype_wins_over_the_filename(self):
        """A connector export keeps its source's name: `Q3 deck` stored as a PDF."""
        assert cited_page({"filetype": "pdf", "filename": "notes.md", "page_num": 5}) == 5
        assert cited_page({"filetype": "md", "filename": "deck.pdf", "page_num": 5}) is None

    def test_a_dotted_filetype_is_read_without_its_dot(self):
        assert cited_page({"filetype": ".PPTX", "page_num": 2}) == 2

    def test_the_paged_formats_are_liteparses_documents_and_presentations(self):
        """Derived, so a format added to the parser's list cites by page with no second edit."""
        assert {"pdf", "doc", "odt", "rtf", "pptx", "key"} <= PAGED_FORMATS
        assert PAGED_FORMATS.isdisjoint({"docx", "xlsx", "csv", "md", "txt", "html"})

    def test_an_unknown_format_names_no_page(self):
        assert cited_page({"page_num": 1}) is None

    @pytest.mark.parametrize("page", [0, None, "3", True, -1])
    def test_a_paged_format_without_a_real_page_names_none(self, page):
        assert cited_page({"filetype": "pdf", "page_num": page}) is None


class TestCitationLocator:
    def test_a_pdf_hit_is_cited_by_page(self):
        assert citation_locator({"filetype": "pdf", "page_num": 3}) == ", page 3"

    @pytest.mark.parametrize("filetype", ["md", "txt", "docx", "html", "xlsx", "png"])
    def test_an_unpaged_hit_names_the_document_alone(self, filetype):
        assert citation_locator({"filetype": filetype, "page_num": 1}) == ""
