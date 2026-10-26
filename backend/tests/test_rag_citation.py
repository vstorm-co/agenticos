"""A citation names a page only where the source has pages (#2489)."""

import pytest

from app.services.rag.citation import citation_locator, cited_heading, cited_page


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

    def test_an_unknown_format_names_no_page(self):
        assert cited_page({"page_num": 1}) is None

    @pytest.mark.parametrize("page", [0, None, "3", True, -1])
    def test_a_paged_format_without_a_real_page_names_none(self, page):
        assert cited_page({"filetype": "pdf", "page_num": page}) is None


class TestCitedHeading:
    @pytest.mark.parametrize(
        ("content", "heading"),
        [
            ("## Install\n\nRun make dev.", "Install"),
            ("\n  # Title #  \nbody", "Title"),
            ("###### Deep\tone", "Deep\tone"),
        ],
    )
    def test_the_heading_a_chunk_opens_with(self, content, heading):
        assert cited_heading(content) == heading

    @pytest.mark.parametrize(
        "content",
        ["Body first.\n## Later", "#hashtag, not a heading", "####### seven", "", "   \n  "],
    )
    def test_no_heading_unless_the_first_line_is_one(self, content):
        assert cited_heading(content) is None

    def test_a_long_heading_is_cut(self):
        heading = cited_heading("# " + "x" * 300)
        assert heading is not None
        assert len(heading) == 120
        assert heading.endswith("…")


class TestCitationLocator:
    def test_a_pdf_hit_is_cited_by_page(self):
        assert citation_locator({"filetype": "pdf", "page_num": 3}, "# Refunds\ntext") == ", page 3"

    def test_a_markdown_hit_is_cited_by_its_section(self):
        locator = citation_locator({"filetype": "md", "page_num": 1}, "## Knowledge\ntext")
        assert locator == ', section "Knowledge"'

    def test_a_text_hit_with_no_heading_names_the_document_alone(self):
        assert citation_locator({"filetype": "txt", "page_num": 1}, "plain text") == ""
