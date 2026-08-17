"""What a chunk is, pinned so a future change to the splitters is visible.

These replaced `langchain-text-splitters` (#158), which means every collection
already ingested was chunked by code that is no longer here. The golden lists
below are the record of what the recursive and fixed strategies produce; a diff
against them is a diff against what every existing search index holds, and it
must be a decision rather than an accident.

`markdown` is the deliberate exception. It never applied `chunk_size` at all -
its comment claimed a second pass that did not exist, so a 50 KB section
between two `##` became one chunk, past the input limit of every embedding
model this platform supports. It now runs the recursive splitter over each
section, so its golden list is a *new* one.
"""

from __future__ import annotations

import itertools
import logging

import pytest

from app.services.rag._splitters import (
    DEFAULT_SEPARATORS,
    MarkdownHeaderSplitter,
    RecursiveCharacterSplitter,
    _header_level,
    _split_keeping_separator,
    _split_on_headers,
)
from app.services.rag.config import RAGSettings
from app.services.rag.documents import DocumentProcessor

DOC = """# Retrieval

The knowledge base answers a search with the chunks it stored, so what a
splitter decided is what the agent can see.

## Chunking

Three strategies ship. Each one is a different answer to the same question:
where may a chunk end?

```python
# not a heading - a comment inside a fence
def chunk(text: str) -> list[str]:
    return []
```

### Overlap

Overlap is a ceiling. A chunk repeats as much of the one before it as fits,
which is frequently less than asked for and sometimes nothing at all.

## Storage

pgvector holds the embeddings, one row per chunk.
"""

# Every chunk below is one list element written over two source lines. The
# parentheses are what say so: without them a missing comma and a deliberate
# continuation look identical, and these lists are the record of what every
# ingested collection holds.
RECURSIVE_CHUNKS = [
    (
        "# Retrieval\n\nThe knowledge base answers a search with the chunks it stored, so what a\n"
        "splitter decided is what the agent can see.\n\n## Chunking"
    ),
    (
        "## Chunking\n\nThree strategies ship. Each one is a different answer to the same "
        "question:\nwhere may a chunk end?"
    ),
    (
        "```python\n# not a heading - a comment inside a fence\ndef chunk(text: str) -> list[str]:\n"
        "    return []\n```\n\n### Overlap"
    ),
    (
        "### Overlap\n\nOverlap is a ceiling. A chunk repeats as much of the one before it as "
        "fits,\nwhich is frequently less than asked for and sometimes nothing at all.\n\n## Storage"
    ),
    "## Storage\n\npgvector holds the embeddings, one row per chunk.",
]

FIXED_CHUNKS = [
    (
        "# Retrieval\n\nThe knowledge base answers a search with the chunks it stored, so what a\n"
        "splitter decided is what the agent can see.\n\n## Chunking"
    ),
    (
        "## Chunking\n\nThree strategies ship. Each one is a different answer to the same "
        "question:\nwhere may a chunk end?\n\n```python\n# not a heading - a comment inside a fence"
    ),
    (
        "def chunk(text: str) -> list[str]:\n    return []\n```\n\n### Overlap\n\n"
        "Overlap is a ceiling. A chunk repeats as much of the one before it as fits,"
    ),
    (
        "which is frequently less than asked for and sometimes nothing at all.\n\n## Storage\n\n"
        "pgvector holds the embeddings, one row per chunk."
    ),
]

MARKDOWN_CHUNKS = [
    (
        "# Retrieval  \nThe knowledge base answers a search with the chunks it stored, so what a\n"
        "splitter decided is what the agent can see."
    ),
    (
        "## Chunking  \nThree strategies ship. Each one is a different answer to the same "
        "question:\nwhere may a chunk end?  \n```python\n# not a heading - a comment inside a fence"
    ),
    "def chunk(text: str) -> list[str]:\nreturn []\n```",
    (
        "### Overlap  \nOverlap is a ceiling. A chunk repeats as much of the one before it as "
        "fits,\nwhich is frequently less than asked for and sometimes nothing at all."
    ),
    "## Storage  \npgvector holds the embeddings, one row per chunk.",
]


class TestGoldenChunks:
    def test_the_recursive_strategy_chunks_a_document_this_way(self):
        splitter = RecursiveCharacterSplitter(chunk_size=200, chunk_overlap=40)

        assert splitter.split_text(DOC) == RECURSIVE_CHUNKS

    def test_the_fixed_strategy_chunks_a_document_this_way(self):
        splitter = RecursiveCharacterSplitter(chunk_size=200, chunk_overlap=40, separators=["\n"])

        assert splitter.split_text(DOC) == FIXED_CHUNKS

    def test_the_markdown_strategy_chunks_a_document_this_way(self):
        """Note the lost indentation on `return []`.

        The header splitter strips every line before deciding whether it opens a
        fence, so whitespace inside a fenced block does not survive it. That is
        what the library did, it is what every markdown collection was ingested
        with, and it is the argument for pinning the output rather than the
        intent.
        """
        splitter = MarkdownHeaderSplitter(chunk_size=200, chunk_overlap=40)

        assert splitter.split_text(DOC) == MARKDOWN_CHUNKS

    def test_the_markdown_strategy_now_honours_chunk_size(self):
        """The bug this closes: one `##` section used to be one chunk, whatever
        its size, because `_create_splitter` returned the header splitter alone
        and nothing ran over its output.
        """
        section = "## Long\n\n" + "\n\n".join(f"Paragraph {i} of the section." for i in range(200))

        chunks = MarkdownHeaderSplitter(chunk_size=300, chunk_overlap=0).split_text(section)

        assert len(chunks) > 1
        assert max(len(chunk) for chunk in chunks) <= 300

    def test_a_chunk_never_crosses_a_header(self):
        text = "# One\n\nalpha\n\n# Two\n\nbeta\n"

        chunks = MarkdownHeaderSplitter(chunk_size=4000, chunk_overlap=0).split_text(text)

        assert chunks == ["# One  \nalpha", "# Two  \nbeta"]


class TestRecursiveSplitting:
    def test_the_separator_stays_at_the_front_of_the_piece_that_follows(self):
        """And is therefore written exactly once.

        The pieces already carry their separators, so the merge joins with the
        empty string. Joining with the separator instead - the obvious way to
        write it - doubles every blank line in the corpus.
        """
        text = "alpha\n\nbeta\n\ngamma"

        chunks = RecursiveCharacterSplitter(chunk_size=8, chunk_overlap=0).split_text(text)

        assert chunks == ["alpha", "beta", "gamma"]
        assert "\n\n\n" not in "".join(chunks)

    def test_overlap_is_a_ceiling_rather_than_a_guarantee(self):
        """A chunk repeats as much of the one before it as still fits, which is
        frequently less than `chunk_overlap` and sometimes nothing. A splitter
        that guaranteed the number would be a different splitter.
        """
        text = " ".join(f"word{i:02d}" for i in range(20))

        chunks = RecursiveCharacterSplitter(chunk_size=30, chunk_overlap=20).split_text(text)

        assert len(chunks) > 1
        overlaps = [
            len(previous) - previous.rfind(following.split(" ")[0])
            for previous, following in itertools.pairwise(chunks)
        ]
        assert all(overlap <= 20 for overlap in overlaps)
        assert any(overlap < 20 for overlap in overlaps)

    def test_a_piece_with_no_separator_left_is_emitted_whole_and_reported(self, caplog):
        """It is not hard-cut. A chunk longer than the embedding model accepts
        fails at the far end of the pipeline, so the warning is the only place
        this is visible before then.
        """
        splitter = RecursiveCharacterSplitter(chunk_size=10, chunk_overlap=0, separators=["\n"])

        with caplog.at_level(logging.WARNING):
            chunks = splitter.split_text("short\n" + "x" * 40)

        assert chunks == ["short", "\n" + "x" * 40]
        assert "no separator left" in caplog.text

    def test_a_piece_exactly_at_the_size_limit_is_emitted_without_a_warning(self, caplog):
        """It is within the limit, not past it.

        The comparison that routes a piece here is `<`, inherited from the port
        and load-bearing - widening it to `<=` would move every chunk boundary in
        every collection already ingested. So a 512-character line under the
        `fixed` strategy with `chunk_size=512` arrives at the oversized branch
        and is emitted whole, correctly. Warning about it sends an operator
        looking for a chunk an embedding model will reject, and there is none.
        """
        splitter = RecursiveCharacterSplitter(chunk_size=10, chunk_overlap=0, separators=["\n"])

        with caplog.at_level(logging.WARNING):
            chunks = splitter.split_text("y" * 10)

        assert chunks == ["y" * 10]
        assert caplog.text == ""

    def test_a_paragraph_too_long_to_keep_is_split_on_the_next_separator_down(self):
        """The first piece is already oversized, so nothing is pending when the
        recursion starts - the case that decides whether a document opening on
        one long paragraph is chunked or emitted whole.
        """
        text = "word " * 40 + "\n\ntail"

        chunks = RecursiveCharacterSplitter(chunk_size=50, chunk_overlap=0).split_text(text)

        assert len(chunks) > 1
        assert max(len(chunk) for chunk in chunks) <= 50
        assert chunks[-1].endswith("tail")

    def test_text_with_no_separator_at_all_is_split_between_characters(self):
        chunks = RecursiveCharacterSplitter(chunk_size=100, chunk_overlap=0).split_text("x" * 250)

        assert [len(chunk) for chunk in chunks] == [100, 100, 50]

    def test_a_separator_that_does_not_occur_leaves_the_text_alone(self):
        splitter = RecursiveCharacterSplitter(chunk_size=100, chunk_overlap=0, separators=["\n"])

        assert splitter.split_text("one line") == ["one line"]

    def test_whitespace_only_text_produces_no_chunks(self):
        """An empty chunk is a row in the vector store that can never match."""
        splitter = RecursiveCharacterSplitter(chunk_size=8, chunk_overlap=0)

        assert splitter.split_text("     \n\n     ") == []

    def test_empty_text_produces_no_chunks(self):
        assert RecursiveCharacterSplitter(chunk_size=100, chunk_overlap=0).split_text("") == []

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"chunk_size": 0, "chunk_overlap": 0}, "chunk_size must be greater than 0"),
            ({"chunk_size": 10, "chunk_overlap": -1}, "chunk_overlap must not be negative"),
            ({"chunk_size": 10, "chunk_overlap": 11}, "must not exceed chunk_size"),
            (
                {"chunk_size": 10, "chunk_overlap": 0, "separators": []},
                "separators must not be empty",
            ),
        ],
    )
    def test_sizes_that_cannot_chunk_are_refused_at_construction(self, kwargs, message):
        with pytest.raises(ValueError, match=message):
            RecursiveCharacterSplitter(**kwargs)


class TestSplitKeepingSeparator:
    def test_the_empty_separator_splits_between_every_character(self):
        assert _split_keeping_separator("abc", "") == ["a", "b", "c"]

    def test_a_leading_separator_does_not_produce_an_empty_first_piece(self):
        assert _split_keeping_separator("\nalpha\nbeta", "\n") == ["\nalpha", "\nbeta"]


class TestHeaderLevel:
    @pytest.mark.parametrize(
        ("line", "level"),
        [
            ("# One", 1),
            ("## Two", 2),
            ("### Three", 3),
            ("#", 1),
            ("###", 3),
            ("#### Four", None),
            ("#nospace", None),
            ("not a header", None),
            ("", None),
        ],
    )
    def test_a_marker_only_opens_a_header_when_a_space_or_nothing_follows(self, line, level):
        assert _header_level(line) == level


class TestHeaderSections:
    def test_a_hash_inside_a_fenced_block_is_code_rather_than_a_heading(self):
        text = "# Title\n\n```bash\n# git log, not a heading\n```\n\n## Real\n\nbody\n"

        assert _split_on_headers(text) == [
            "# Title  \n```bash\n# git log, not a heading\n```",
            "## Real  \nbody",
        ]

    def test_a_tilde_fence_hides_a_heading_too(self):
        text = "# Title\n\n~~~\n## not a heading\n~~~\n\n## Real\n\nbody\n"

        assert _split_on_headers(text) == [
            "# Title  \n~~~\n## not a heading\n~~~",
            "## Real  \nbody",
        ]

    def test_an_unclosed_fence_swallows_the_rest_of_the_document(self):
        """Which is what the markdown a parser produced actually looks like when
        a PDF page ends mid-listing, and is the library's behaviour too."""
        assert _split_on_headers("# T\n\n```\n# inside\n") == ["# T  \n```\n# inside\n"]

    def test_a_title_stays_with_the_section_that_follows_it(self):
        """A lone `# Title` is a chunk nothing can ever retrieve."""
        assert _split_on_headers("# A\n## B\nbody\n") == ["# A  \n## B\nbody"]

    def test_a_title_with_prose_under_it_is_its_own_section(self):
        assert _split_on_headers("# A\ntext\n## B\nbody\n") == ["# A\ntext", "## B\nbody"]

    def test_two_headers_at_the_same_level_never_merge(self):
        assert _split_on_headers("# A\n# B\nbody\n") == ["# A", "# B\nbody"]

    def test_text_before_the_first_header_is_its_own_section(self):
        assert _split_on_headers("intro\n\n# A\nbody\n") == ["intro", "# A\nbody"]

    def test_a_document_with_no_headers_is_one_section(self):
        assert _split_on_headers("just prose\n\nand more\n") == ["just prose  \nand more"]

    def test_leading_blank_lines_are_not_a_section(self):
        assert _split_on_headers("\n\n\n") == []

    def test_an_empty_document_has_no_sections(self):
        assert _split_on_headers("") == []
        assert MarkdownHeaderSplitter(chunk_size=100, chunk_overlap=0).split_text("") == []


class TestStrategySelection:
    """`_create_splitter` returns one type now, so `process_file` cannot branch.

    It used to hand back two classes whose `split_text` returned different
    shapes - langchain `Document` objects for markdown, strings for everything
    else - and the caller carried an `is_markdown_splitter` flag to unwrap one
    and not the other.
    """

    @pytest.mark.parametrize(
        ("strategy", "expected"),
        [
            ("markdown", MarkdownHeaderSplitter),
            ("fixed", RecursiveCharacterSplitter),
            ("recursive", RecursiveCharacterSplitter),
        ],
    )
    def test_a_strategy_selects_its_splitter(self, strategy, expected):
        settings = RAGSettings(chunking_strategy=strategy, chunk_size=256, chunk_overlap=32)

        assert isinstance(DocumentProcessor._create_splitter(settings), expected)

    def test_the_fixed_strategy_only_ever_breaks_on_a_line_end(self):
        settings = RAGSettings(chunking_strategy="fixed", chunk_size=256, chunk_overlap=32)

        splitter = DocumentProcessor._create_splitter(settings)

        assert isinstance(splitter, RecursiveCharacterSplitter)
        assert splitter.separators == ("\n",)

    def test_the_default_strategy_falls_back_through_paragraph_line_word_character(self):
        settings = RAGSettings(chunking_strategy="recursive", chunk_size=256, chunk_overlap=32)

        splitter = DocumentProcessor._create_splitter(settings)

        assert isinstance(splitter, RecursiveCharacterSplitter)
        assert splitter.separators == DEFAULT_SEPARATORS
