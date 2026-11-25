"""Text a model reads but takes no orders from, set apart so it cannot end its own section.

A prompt that puts a person's or an agent's text between literal tags lets that
text close the tag and write past it, where it reads as the prompt's own words. A
Markdown fence longer than any run of backticks the text holds cannot be closed
from inside it, and keeps the text byte for byte, so a passage the model quotes
from it still matches the original.
"""

_SHORTEST_FENCE = 3


def _longest_run(text: str) -> int:
    """The longest run of backticks in `text`, by substring search alone.

    A conversation can hold millions of short runs, and listing them all to find
    the longest costs a request seconds and megabytes before any budget is checked.
    Doubling and then halving a probe asks only a few searches of the text.
    """
    found, step = 0, 1
    while "`" * (found + step) in text:
        found += step
        step *= 2
    while step > 1:
        step //= 2
        if "`" * (found + step) in text:
            found += step
    return found


def fence(text: str) -> str:
    """`text` between two fence lines that no line of it can match."""
    bar = "`" * max(_SHORTEST_FENCE, _longest_run(text) + 1)
    return f"{bar}\n{text}\n{bar}"


def fenced_section(tag: str, text: str) -> str:
    """`text` fenced inside `<tag>`: a section of data a prompt can name by its tag."""
    return f"<{tag}>\n{fence(text)}\n</{tag}>"
