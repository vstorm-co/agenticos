"""The excerpt an upload answers with, and what it refuses to answer with."""

from app.services.file_upload import PREVIEW_CHARS, PREVIEW_LINES, make_preview


def test_a_file_with_no_text_has_no_preview():
    """An image, and a parse that failed, are the same thing to a client.

    `None` rather than `""`: a card renders its thumbnail or its name alone, and
    an empty string would put an empty quote block under both.
    """
    assert make_preview(None) is None
    assert make_preview("") is None


def test_whitespace_only_text_is_not_a_preview():
    assert make_preview("\n\n   \n") is None


def test_the_preview_is_the_first_lines_and_nothing_after_them():
    text = "\n".join(f"line {i}" for i in range(20))

    preview = make_preview(text)

    assert preview == "line 0\nline 1\nline 2"
    assert preview is not None
    assert len(preview.splitlines()) == PREVIEW_LINES


def test_one_enormous_line_is_bounded_by_characters():
    """The line bound alone is not a bound. A minified JSON file is one line."""
    preview = make_preview("x" * 10_000)

    assert preview == "x" * PREVIEW_CHARS


def test_a_shorter_file_is_returned_whole():
    assert make_preview("hello, world") == "hello, world"
