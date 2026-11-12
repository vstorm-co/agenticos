"""Three-way merge of a skill: the version a fork started from, the fork, and main.

Catching a fork up with main, and moving a fork's changes to main, both start from
the same three texts. A part one side changed and the other left alone takes that
side's text by itself; a part both sides changed the same way is taken once; a part
they changed differently is a conflict, which a person settles - the model only
proposes a combined text.

The body is merged by lines, as diff3 does: base, fork and main are split into
lines, each side is matched against the base, and only the stretches of the base
that both sides kept bound the parts in between. So two edits on neighbouring lines
are one conflict, as they are in diff3 - nothing tells which order they belong in.
Line endings are read as LF: the editor saves LF, and a text that only swapped its
line endings has changed nothing a person would see.

The description is one value, merged whole, and files are merged by name on their
digests. Nothing here reads the database; the catch-up service stores the parts.

Matching a side against the base compares every pair of equal lines, and goes over
them again for each stretch it splits the texts into, so a line that repeats costs CPU
cubic in how often it does. Lines that repeat - the blank lines between a skill's
paragraphs, a `---` rule, a code fence - therefore never anchor the matching: the other
lines are matched first, each occurring at most `MAX_REPEATS` times, and in each stretch
between those matches the repeated lines are paired in order. A merge is refused,
before it runs, only for a side longer than `MAX_LINES`.
"""

from bisect import bisect_left
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from difflib import Match, SequenceMatcher
from enum import StrEnum

MAX_LINES = 5000
"""The most lines a side may hold for the merge to run."""

MAX_REPEATS = 4
"""How often a line may occur in the base or a side and still anchor the matching; a line
occurring more often is paired in order between the anchors, as a blank line is."""


class MergeTooLarge(ValueError):
    """The texts are too long to merge line by line."""


class PartState(StrEnum):
    """Which side a part of the merge comes from."""

    SAME = "same"
    """Neither side changed it."""
    FORK = "fork"
    """Only the fork changed it."""
    MAIN = "main"
    """Only main changed it."""
    BOTH = "both"
    """Both sides changed it to the same text."""
    CONFLICT = "conflict"
    """Both sides changed it, differently."""


@dataclass(frozen=True)
class MergePart:
    """One stretch of the merged text, with what each of the three said there.

    Attributes:
        state: Which side it comes from, or that the sides disagree.
        base: The text where the fork started.
        fork: The fork's text.
        main: Main's text.
    """

    state: PartState
    base: str
    fork: str
    main: str

    @property
    def merged(self) -> str | None:
        """The part's text in the merge, or `None` for a conflict a person settles."""
        return _pick(self.state, self.base, self.fork, self.main)


@dataclass(frozen=True)
class FileMerge:
    """One file of the merge, by its digest on each side; `None` where it is absent.

    Attributes:
        name: The file's path within the skill.
        state: Which side it comes from, or that the sides disagree.
        base: Its digest where the fork started.
        fork: Its digest on the fork.
        main: Its digest on main.
    """

    name: str
    state: PartState
    base: str | None
    fork: str | None
    main: str | None

    @property
    def merged(self) -> str | None:
        """The digest the merge keeps; `None` for a file it drops, as for a conflict."""
        return _pick(self.state, self.base, self.fork, self.main)


def merge_text(base: str, fork: str, main: str) -> list[MergePart]:
    """The three texts as consecutive parts, each either agreed or a conflict.

    Joining every part's `merged` text gives the merge, once no part is a conflict.

    Raises:
        MergeTooLarge: A side is past `MAX_LINES`.
    """
    base_lines, fork_lines, main_lines = (_lines(text) for text in (base, fork, main))
    _refuse_too_large(base_lines, fork_lines, main_lines)
    parts: list[MergePart] = []
    at_base = at_fork = at_main = 0
    for kept in _kept_by_both(base_lines, fork_lines, main_lines):
        gap = MergePart(
            _state(
                base_lines[at_base : kept.base],
                fork_lines[at_fork : kept.fork],
                main_lines[at_main : kept.main],
            ),
            "".join(base_lines[at_base : kept.base]),
            "".join(fork_lines[at_fork : kept.fork]),
            "".join(main_lines[at_main : kept.main]),
        )
        if gap.base or gap.fork or gap.main:
            parts.append(gap)
        same = "".join(base_lines[kept.base : kept.base + kept.size])
        if same:
            parts.append(MergePart(PartState.SAME, same, same, same))
        at_base, at_fork, at_main = (
            kept.base + kept.size,
            kept.fork + kept.size,
            kept.main + kept.size,
        )
    return parts


def merged_text(parts: Sequence[MergePart]) -> str | None:
    """The merge of `parts`, or `None` while any of them is a conflict."""
    texts = [part.merged for part in parts]
    if any(text is None for text in texts):
        return None
    return "".join(text for text in texts if text is not None)


def merge_value(base: str, fork: str, main: str) -> MergePart:
    """One value merged whole, as a skill's description is."""
    return MergePart(_state([base], [fork], [main]), base, fork, main)


def merge_files(
    base: Mapping[str, str], fork: Mapping[str, str], main: Mapping[str, str]
) -> list[FileMerge]:
    """Each file named on any side, by name, from the digests each side holds.

    A file one side deleted and the other left alone is dropped; one side deleted
    and the other changed is a conflict.
    """
    return [
        FileMerge(
            name,
            _state([base.get(name)], [fork.get(name)], [main.get(name)]),
            base.get(name),
            fork.get(name),
            main.get(name),
        )
        for name in sorted(base.keys() | fork.keys() | main.keys())
    ]


@dataclass(frozen=True)
class _Kept:
    """A run of `size` lines both sides kept from the base, where it starts in each."""

    base: int
    fork: int
    main: int
    size: int


def _refuse_too_large(base: list[str], fork: list[str], main: list[str]) -> None:
    if max(len(base), len(fork), len(main)) > MAX_LINES:
        raise MergeTooLarge(f"a side holds more than {MAX_LINES} lines")


def _lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").splitlines(keepends=True)


def _kept_by_both(base: list[str], fork: list[str], main: list[str]) -> Iterator[_Kept]:
    """The stretches of the base both sides kept, in order, then an empty one at the end.

    Each side's kept stretches come from matching it against the base; where a
    stretch of one overlaps a stretch of the other, both kept those base lines.
    """
    by_fork = _matched(base, fork)
    by_main = _matched(base, main)
    at_fork = at_main = 0
    while at_fork < len(by_fork) and at_main < len(by_main):
        fork_block, main_block = by_fork[at_fork], by_main[at_main]
        start = max(fork_block.a, main_block.a)
        end = min(fork_block.a + fork_block.size, main_block.a + main_block.size)
        if start < end:
            yield _Kept(
                base=start,
                fork=fork_block.b + start - fork_block.a,
                main=main_block.b + start - main_block.a,
                size=end - start,
            )
        if fork_block.a + fork_block.size < main_block.a + main_block.size:
            at_fork += 1
        else:
            at_main += 1
    yield _Kept(base=len(base), fork=len(fork), main=len(main), size=0)


def _blank(line: str) -> bool:
    return not line.strip()


def _repeated(base: list[str], side: list[str]) -> set[str]:
    """The lines that do not anchor the matching: blank, or past `MAX_REPEATS` in a text."""
    in_base, in_side = Counter(base), Counter(side)
    return {
        line
        for line in in_base.keys() | in_side.keys()
        if _blank(line) or in_base[line] > MAX_REPEATS or in_side[line] > MAX_REPEATS
    }


def _matched(base: list[str], side: list[str]) -> list[Match]:
    """The stretches of the base a side kept, in order, then an empty one at the end.

    The lines that do not repeat are matched first, and a repeated one only extends such
    a match; in each stretch left between two matches, the repeated lines on both sides
    are then paired in order.
    """
    repeated = _repeated(base, side)
    anchored = SequenceMatcher(
        repeated.__contains__, base, side, autojunk=False
    ).get_matching_blocks()
    found: list[Match] = []
    at_base = at_side = 0
    for block in anchored:
        found.extend(
            _in_order(
                base,
                side,
                [i for i in range(at_base, block.a) if base[i] in repeated],
                [j for j in range(at_side, block.b) if side[j] in repeated],
            )
        )
        if block.size:
            found.append(block)
        at_base, at_side = block.a + block.size, block.b + block.size
    return [*_joined(found), Match(len(base), len(side), 0)]


def _joined(matches: list[Match]) -> Iterator[Match]:
    """Matches that run on from one another as one, so a kept stretch is one part."""
    run: Match | None = None
    for match in matches:
        if run is not None and (run.a + run.size, run.b + run.size) == (match.a, match.b):
            run = Match(run.a, run.b, run.size + match.size)
            continue
        if run is not None:
            yield run
        run = match
    if run is not None:
        yield run


def _in_order(
    base: list[str], side: list[str], base_at: list[int], side_at: list[int]
) -> Iterator[Match]:
    """Each repeated line of the base paired with the next equal one of the side after
    the last pair, so the pairs never cross; one with none left stays unpaired."""
    where: dict[str, list[int]] = {}
    for position, line_at in enumerate(side_at):
        where.setdefault(side[line_at], []).append(position)
    after = 0
    for line_at in base_at:
        positions = where.get(base[line_at], [])
        found = bisect_left(positions, after)
        if found == len(positions):
            continue
        after = positions[found] + 1
        yield Match(line_at, side_at[positions[found]], 1)


def _state[T](base: Sequence[T], fork: Sequence[T], main: Sequence[T]) -> PartState:
    fork_changed, main_changed = list(fork) != list(base), list(main) != list(base)
    if not fork_changed and not main_changed:
        return PartState.SAME
    if not main_changed:
        return PartState.FORK
    if not fork_changed:
        return PartState.MAIN
    return PartState.BOTH if list(fork) == list(main) else PartState.CONFLICT


def _pick[T](state: PartState, base: T, fork: T, main: T) -> T | None:
    if state is PartState.SAME:
        return base
    if state in (PartState.FORK, PartState.BOTH):
        return fork
    if state is PartState.MAIN:
        return main
    return None
