"""The opening of a text body, for a card that hints at content without carrying it."""

EXCERPT_LINES = 8
EXCERPT_CHARS = 320


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
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        closing = next(
            (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
            None,
        )
        if closing is not None:
            start = closing + 1
    while start < len(lines) and not lines[start].strip():
        start += 1
    return "\n".join(lines[start : start + EXCERPT_LINES])[:EXCERPT_CHARS].rstrip()
