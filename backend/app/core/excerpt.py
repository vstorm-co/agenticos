"""The opening of a text body, for a card that hints at content without carrying it."""

from collections.abc import Iterator
from itertools import chain, dropwhile, islice

EXCERPT_LINES = 8
EXCERPT_CHARS = 320


def _lines(text: str) -> Iterator[str]:
    """The body's lines one at a time, each cut to what an excerpt could show.

    Lazily, rather than `splitlines()`: a listing summarizes up to fifty bodies,
    and splitting a large one allocates every line of it to keep eight.
    """
    start = 0
    while True:
        end = text.find("\n", start)
        stop = len(text) if end == -1 else end
        yield text[start : min(stop, start + EXCERPT_CHARS)].rstrip("\r")
        if end == -1:
            return
        start = end + 1


def _shown(lines: list[str]) -> str:
    return "\n".join(lines)[:EXCERPT_CHARS].rstrip()


def excerpt(text: str) -> str:
    """The first lines of a body, bounded so a listing never carries the body itself.

    Leading YAML front matter is dropped: it restates what the card already
    shows - the name and the description - and would fill the peek with `name:`
    lines. Blank lines before the first real line go too; the ones after it stay,
    because they are what separates a heading from its paragraph.

    Returns:
        At most `EXCERPT_LINES` lines and `EXCERPT_CHARS` characters, or `""`
        for a body with nothing to show.
    """
    lines = _lines(text)
    head = list(islice(lines, 1))
    if head and head[0].strip() == "---":
        opening = head
        for line in lines:
            if line.strip() == "---":
                break
            if len(opening) < EXCERPT_LINES:
                opening.append(line)
        else:
            # Never closed, so it was not front matter: the body shows from its
            # first line.
            return _shown(opening)
        head = []
    body = dropwhile(lambda line: not line.strip(), chain(head, lines))
    return _shown(list(islice(body, EXCERPT_LINES)))
