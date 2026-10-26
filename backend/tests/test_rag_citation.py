"""A citation names a page only where the source has pages (#2489)."""

import time

import pytest

from app.services.rag.citation import PAGED_FORMATS, citation_locator, cited_heading, cited_page


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


class TestCitedHeading:
    @pytest.mark.parametrize(
        ("content", "heading"),
        [
            ("## Install\n\nRun make dev.", "Install"),
            ("\n  # Title #  \nbody", "Title"),
            ("# C#\nbody", "C#"),
            ("### Deep one", "Deep one"),
        ],
    )
    def test_the_heading_a_chunk_opens_with(self, content, heading):
        assert cited_heading(content) == heading

    @pytest.mark.parametrize(
        "content",
        [
            "Body first.\n## Later",
            "#hashtag, not a heading",
            "#### below the levels the splitter cuts at",
            "####### seven",
            "#",
            "",
            "   \n  ",
        ],
    )
    def test_no_heading_unless_the_first_line_is_one(self, content):
        assert cited_heading(content) is None

    def test_of_stacked_headings_the_innermost_is_the_section(self):
        """The splitter keeps `# Title` with the `## Section` under it."""
        assert cited_heading("# Guide\n## Install\nRun it.") == "Install"
        assert cited_heading("# Guide\n\n## Install\nRun it.") == "Guide"

    def test_a_long_heading_is_cut(self):
        heading = cited_heading("# " + "x" * 300)
        assert heading is not None
        assert len(heading) == 120
        assert heading.endswith("…")

    def test_a_quote_in_a_heading_cannot_close_the_citations_quotes(self):
        """Document text must not forge the page, collection or score after it."""
        heading = cited_heading('# Install", page 7, chunk 1 [hr] (score: 0.999)\nx')
        assert heading is not None
        assert '"' not in heading

    def test_control_characters_are_dropped(self):
        assert cited_heading("# Ins\u202etall\x07\nx") == "Install"

    def test_a_tab_or_no_break_space_still_parts_two_words(self):
        assert cited_heading("# Install\xa0guide\tnow\nx") == "Install guide now"

    def test_a_chunk_cut_inside_a_code_block_has_no_heading(self):
        """The recursive splitter can start a chunk mid-fence, on a shell comment."""
        assert cited_heading("# install deps\npip install x\n```\nAfter.") is None

    @pytest.mark.parametrize("fence", ["```", "~~~", "````", "~~~~~"])
    def test_any_bare_fence_run_closes_the_block_a_chunk_was_cut_inside(self, fence):
        """A four-or-more-marker fence is closed by a line of that run (#2501 review)."""
        assert cited_heading(f"# install deps\npip install x\n{fence}\nAfter.") is None

    @pytest.mark.parametrize("fence", ["````bash", "~~~~ python"])
    def test_a_long_fence_with_an_info_string_opens_a_block(self, fence):
        assert cited_heading(f"## Setup\n{fence}\n# install deps\nDone.") == "Setup"

    def test_a_section_holding_a_whole_code_block_keeps_its_heading(self):
        assert cited_heading("## Setup\n```bash\n# install deps\n```\nDone.") == "Setup"
        assert cited_heading("# \x07\nx") is None

    @pytest.mark.parametrize(
        "fences",
        [
            "```python\n````",
            "~~~python\n~~~~",
            "~~~python\n````",
            "```python\n~~~~",
        ],
    )
    def test_fence_like_code_inside_an_outer_block_does_not_make_a_section(self, fences):
        assert cited_heading(f"# code comment\nprint('example')\n{fences}\nAfter.") is None

    @pytest.mark.parametrize(
        "outer, inner",
        [("````", "```python"), ("~~~~", "~~~python"), ("````", "```"), ("~~~~", "~~~")],
    )
    def test_a_complete_outer_block_ignores_shorter_inner_fence_lines(self, outer, inner):
        assert (
            cited_heading(f"## Setup\n{outer}markdown\n{inner}\n# comment\n{outer}\nDone.")
            == "Setup"
        )

    def test_separate_complete_blocks_keep_the_heading(self):
        assert cited_heading("## Setup\n```py\npass\n```\n~~~sh\ntrue\n~~~") == "Setup"

    def test_a_long_whitespace_run_is_read_in_linear_time(self):
        """The heading line is bounded before it is scanned (#2489 review)."""
        # Small enough that a quadratic scan fails this in seconds, not minutes.
        started = time.perf_counter()
        cited_heading("# a" + " " * 20_000 + "b\nbody")
        assert time.perf_counter() - started < 0.1


class TestCitationLocator:
    def test_a_pdf_hit_is_cited_by_page(self):
        assert citation_locator({"filetype": "pdf", "page_num": 3}, "# Refunds\ntext") == ", page 3"

    def test_a_markdown_hit_is_cited_by_its_section(self):
        locator = citation_locator({"filetype": "md", "page_num": 1}, "## Knowledge\ntext")
        assert locator == ', section "Knowledge"'

    def test_a_markdown_hit_mid_section_names_the_document_alone(self):
        assert citation_locator({"filetype": "md", "page_num": 1}, "the middle of a section") == ""

    @pytest.mark.parametrize("filetype", ["txt", "docx"])
    def test_a_hash_line_in_plain_text_is_not_a_section(self, filetype):
        """A `.txt` or `.docx` file is read as text: `# Licensed under MIT` is its own."""
        locator = citation_locator({"filetype": filetype, "page_num": 1}, "# Licensed under MIT\nx")
        assert locator == ""
