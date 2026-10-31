"""How alike two texts are, as a number a reader can check, without a model.

One scorer shared by the `text.compare` workflow node, the approval edit ratio
(a reviewer's edit to a draft) and evals, so a number means the same live and
offline. It is plain, synchronous and deterministic: no I/O, no database, no
randomness and no model call. A caller on the event loop runs :func:`compare`
through `asyncio.to_thread`; the worst case, two texts at
:data:`MAX_TEXT_CHARS`, is 2 to 4 seconds of CPU (measured: 2.2 s over two
symbols, 3.6 s over 1,000, 3.0 s over 20,000) in memory proportional to the text (about 25 MB at the limit).

Three methods, each a share between 0 (nothing in common) and 1 (the same
after normalisation):

- `char_ratio`: the share of characters an editor would not have to touch,
  `1 - edit_distance / longer length`, the edit distance being the exact
  Levenshtein distance (insert, delete or replace one character).
- `token_f1`: the share of words in common, order ignored. The F1 of the
  multiset overlap of the two word lists, `2 * overlap / (words a + words b)`.
- `line_diff`: the share of lines unchanged, `1 - edit_distance / more lines`
  with whole lines as the units.

Both texts are normalised first, in this order: Unicode NFC (always, so a
composed and a decomposed accent are not an edit), `\\r\\n` and `\\r` to `\\n`
(always), :func:`strip_quoted`, case folding, punctuation removal, whitespace
collapsing. Everything after the line endings is opt-in through
:class:`Normalization`. Scores are rounded to six decimals so the same pair
always serialises to the same JSON.

The cost is bounded: the edit distance is bit-parallel (:func:`levenshtein`),
`O(len(a) * len(b) / word)` time and O(len(b)) memory with no input that is worse than another of
the same size. `difflib` is deliberately not used; its matching is quadratic
for some inputs (a 20,000-word text over a four-word vocabulary took 20 s).
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from typing import Final, Literal, assert_never

from app.core.exceptions import ValidationError
from app.core.field_errors import field_details

__all__ = [
    "MAX_TEXT_CHARS",
    "Method",
    "Normalization",
    "Similarity",
    "Unit",
    "compare",
    "levenshtein",
    "normalize",
    "strip_quoted",
    "tokens",
]

MAX_TEXT_CHARS: Final = 100_000

Method = Literal["char_ratio", "token_f1", "line_diff"]
Unit = Literal["characters", "tokens", "lines"]

_ORIGINAL_MESSAGE = re.compile(r"^-{2,}\s*original message\s*-{2,}$", re.IGNORECASE)
_WORD = re.compile(r"\w+")
_SCORE_PLACES: Final = 6
_CACHE_ALL_UP_TO: Final = 4096


@dataclass(frozen=True)
class Normalization:
    """What to ignore when comparing; Unicode NFC and line endings always are."""

    case: bool = False
    """`casefold()` both texts."""
    whitespace: bool = False
    """Per line: runs of whitespace become one space and the line is stripped;
    blank lines are dropped."""
    punctuation: bool = False
    """Drop every character whose Unicode category starts with `P`."""
    strip_quoted: bool = False
    """Apply :func:`strip_quoted` first."""


@dataclass(frozen=True)
class Similarity:
    """One comparison: the score, its complement and the size of each side."""

    method: Method
    score: float
    """0 to 1, 1.0 the same after normalisation; `round(raw, 6)`."""
    changed_ratio: float
    """`round(1 - raw, 6)`: the share that differs."""
    unit: Unit
    a_units: int
    """Characters, tokens or lines of `a` after normalisation, per `unit`."""
    b_units: int


def _unix_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def strip_quoted(text: str) -> str:
    """Leave out the quoted reply and the signature of a plain-text mail.

    Line based, after line endings are made `\\n`:

    1. the text is cut at the first line that is exactly `-- ` or `--` (the RFC
       3676 signature separator) or an `----- Original Message -----` line; that
       line and everything after it go;
    2. every line whose first non-whitespace character is `>` goes;
    3. a non-blank line ending in `:` goes when the next non-blank line is a
       quoted one (the attribution: `On Mon, Ann wrote:`, `W dniu ...
       napisał(a):`, `Am ... schrieb ...:`), in any language;
    4. trailing blank lines are stripped.

    This is a heuristic for plain-text mail, shared with the message parser. It
    does not catch HTML quotes, a top-posted reply whose quote is not marked
    with `>`, an attribution wrapped over two lines or a signature with no
    separator.
    """
    lines = _unix_newlines(text).split("\n")
    for index, line in enumerate(lines):
        if line in ("-- ", "--") or _ORIGINAL_MESSAGE.match(line):
            lines = lines[:index]
            break

    quoted = [line.lstrip().startswith(">") for line in lines]
    # One backward pass: whether the nearest non-blank line after each one is quoted.
    attribution = [False] * len(lines)
    next_is_quoted = False
    for index in range(len(lines) - 1, -1, -1):
        attribution[index] = next_is_quoted
        if lines[index].strip():
            next_is_quoted = quoted[index]

    kept = [
        line
        for index, line in enumerate(lines)
        if not quoted[index] and not (attribution[index] and line.rstrip().endswith(":"))
    ]

    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept)


def normalize(text: str, how: Normalization) -> str:
    """Normalise `text` for comparison, in the order the module docstring gives."""
    text = _unix_newlines(unicodedata.normalize("NFC", text))
    if how.strip_quoted:
        text = strip_quoted(text)
    if how.case:
        text = text.casefold()
    if how.punctuation:
        text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("P"))
    if how.whitespace:
        lines = (" ".join(line.split()) for line in text.split("\n"))
        text = "\n".join(line for line in lines if line)
    return text


def tokens(text: str) -> list[str]:
    """The words of `text`: runs of letters, digits and underscores, any script.

    It splits on apostrophes and does not segment scripts written without
    spaces; a language-aware tokeniser can replace it behind the same name.
    """
    return _WORD.findall(text)


def levenshtein(a: Sequence[Hashable], b: Sequence[Hashable]) -> int:
    """The exact edit distance between two sequences (insert, delete, replace).

    The bit-parallel algorithm of Myers (1999) in Hyyrö's (2001) formulation
    over Python integers: a few big-integer operations per item of the longer
    sequence, so `O(len(a) * len(b) / word)` for any content. The shorter
    sequence is the bit vector. Memory is O(len(b)): see the mask cache below.
    """
    if len(a) < len(b):
        a, b = b, a
    pattern, text = b, a
    m = len(pattern)
    if m == 0:
        return len(text)

    positions: dict[Hashable, list[int]] = {}
    for position, item in enumerate(pattern):
        positions.setdefault(item, []).append(position)

    def build(places: list[int]) -> int:
        bits = bytearray((m >> 3) + 1)
        for place in places:
            bits[place >> 3] |= 1 << (place & 7)
        return int.from_bytes(bits, "little")

    # A mask is as wide as the pattern, so keeping one per distinct item would
    # take memory quadratic in the length for a large alphabet. Only items
    # frequent enough to be worth it are kept (at most m / threshold masks, so
    # O(m) bytes); a rarer item's mask is built when the text reaches it.
    threshold = 1 if m <= _CACHE_ALL_UP_TO else max(64, m >> 9)
    kept = {item: build(places) for item, places in positions.items() if len(places) >= threshold}

    full = (1 << m) - 1
    last = 1 << (m - 1)
    positive, negative, distance = full, 0, m
    for item in text:
        eq = kept.get(item, 0)
        if not eq and item in positions:
            eq = build(positions[item])
        xv = eq | negative
        xh = ((((eq & positive) + positive) ^ positive) | eq) & full
        ph = (negative | ~(xh | positive)) & full
        mh = positive & xh
        if ph & last:
            distance += 1
        elif mh & last:
            distance -= 1
        ph = ((ph << 1) | 1) & full
        mh = (mh << 1) & full
        positive = (mh | ~(xv | ph)) & full
        negative = ph & xv
    return distance


def _share(a: Sequence[Hashable], b: Sequence[Hashable]) -> float:
    """`1 - edit distance / longer length`, 1.0 for two empty sequences."""
    longest = max(len(a), len(b))
    if longest == 0:
        return 1.0
    return 1 - levenshtein(a, b) / longest


def _token_f1(a: str, b: str) -> tuple[float, int, int]:
    ta, tb = tokens(a), tokens(b)
    if not ta and not tb:
        return 1.0, 0, 0
    overlap = sum((Counter(ta) & Counter(tb)).values())
    return 2 * overlap / (len(ta) + len(tb)), len(ta), len(tb)


def compare(
    a: str,
    b: str,
    *,
    method: Method = "char_ratio",
    normalization: Normalization = Normalization(),
) -> Similarity:
    """Score how alike `a` and `b` are by `method`, after `normalization`.

    Raises:
        ValidationError: A text is over :data:`MAX_TEXT_CHARS` characters,
            counted before normalisation; `a` is checked first.
    """
    for name, text in (("a", a), ("b", b)):
        if len(text) > MAX_TEXT_CHARS:
            raise ValidationError(
                message=f"The text is over {MAX_TEXT_CHARS:,} characters",
                details=field_details(
                    name, f"The text is over {MAX_TEXT_CHARS:,} characters", limit=MAX_TEXT_CHARS
                ),
            )
    a, b = normalize(a, normalization), normalize(b, normalization)

    raw: float
    unit: Unit
    if method == "char_ratio":
        raw, unit, a_units, b_units = _share(a, b), "characters", len(a), len(b)
    elif method == "token_f1":
        raw, a_units, b_units = _token_f1(a, b)
        unit = "tokens"
    elif method == "line_diff":
        la = a.split("\n") if a else []
        lb = b.split("\n") if b else []
        raw, unit, a_units, b_units = _share(la, lb), "lines", len(la), len(lb)
    else:
        assert_never(method)
    return Similarity(
        method=method,
        score=round(raw, _SCORE_PLACES),
        changed_ratio=round(1 - raw, _SCORE_PLACES),
        unit=unit,
        a_units=a_units,
        b_units=b_units,
    )
