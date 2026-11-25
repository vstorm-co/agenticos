"""Text a model reads but takes no orders from, set apart so it cannot end its own section.

A prompt that puts a person's or an agent's text between literal tags lets that
text close the tag and write past it, where it reads as the prompt's own words. A
Markdown fence longer than any run of backticks the text holds cannot be closed
from inside it, and keeps the text byte for byte, so a passage the model quotes
from it still matches the original.
"""

import re

_BACKTICKS = re.compile(r"`+")
_SHORTEST_FENCE = 3


def fence(text: str) -> str:
    """`text` between two fence lines that no line of it can match."""
    longest = max((len(run) for run in _BACKTICKS.findall(text)), default=0)
    bar = "`" * max(_SHORTEST_FENCE, longest + 1)
    return f"{bar}\n{text}\n{bar}"


def fenced_section(tag: str, text: str) -> str:
    """`text` fenced inside `<tag>`: a section of data a prompt can name by its tag."""
    return f"<{tag}>\n{fence(text)}\n</{tag}>"
