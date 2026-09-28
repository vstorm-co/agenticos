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
