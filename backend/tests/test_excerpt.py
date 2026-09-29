"""The bounded opening of a skill or context body that listing cards peek at."""

from app.core.excerpt import EXCERPT_CHARS, EXCERPT_LINES, excerpt


def test_front_matter_is_dropped_because_the_card_already_shows_it():
    body = "---\nname: refunds\ndescription: How refunds work\n---\n\n# Refunds\n\nCheck the order."

    assert excerpt(body) == "# Refunds\n\nCheck the order."


def test_an_unclosed_front_matter_fence_is_content_not_metadata():
    assert excerpt("---\nnot front matter") == "---\nnot front matter"


def test_leading_blank_lines_go_and_inner_ones_stay():
    assert excerpt("\n\n  \n# Title\n\nBody") == "# Title\n\nBody"


def test_it_is_bounded_by_lines_and_by_characters():
    many_lines = "\n".join(f"line {n}" for n in range(EXCERPT_LINES + 5))
    one_long_line = "x" * (EXCERPT_CHARS * 2)

    assert excerpt(many_lines).count("\n") == EXCERPT_LINES - 1
    assert len(excerpt(one_long_line)) == EXCERPT_CHARS


def test_an_empty_body_has_nothing_to_show():
    assert excerpt("") == ""
    assert excerpt("---\nname: x\n---\n\n") == ""


def test_a_large_body_is_read_lazily_rather_than_split_whole():
    # A listing summarizes up to fifty bodies; `splitlines()` on each allocated
    # every line of it to keep eight.
    class Body(str):
        def splitlines(self, keepends: bool = False) -> list[str]:
            raise AssertionError("split the whole body")

    body = Body("# Title\n" + "short\n" * 100_000)

    assert excerpt(body) == "# Title\n" + "\n".join(["short"] * (EXCERPT_LINES - 1))


def test_windows_line_endings_leave_no_carriage_returns():
    assert excerpt("---\r\nname: x\r\n---\r\n# Title\r\nBody") == "# Title\nBody"


def test_a_long_front_matter_is_dropped_whole():
    fields = "\n".join(f"field_{n}: value" for n in range(EXCERPT_LINES * 2))

    assert excerpt(f"---\n{fields}\n---\n# Title") == "# Title"
    # And an unclosed one still shows only its first lines.
    assert excerpt(f"---\n{fields}").count("\n") == EXCERPT_LINES - 1
