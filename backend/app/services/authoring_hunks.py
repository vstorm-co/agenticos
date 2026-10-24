"""Where a proposed change lands in a draft, and whether it still can.

Pure functions over text and specs, so the rules can be read and tested apart
from the database.

**An instructions hunk is anchored by position, not by its text alone.** The
same line can occur twice, and an insertion has no text to find, so a hunk
keeps where its passage sat when it was proposed and the characters around it.
It applies where that anchor still resolves: the same passage with the same
surroundings, or - when the passage has moved - the only place the passage now
occurs. Anything else is *stale*: the passage is gone, changed or ambiguous, and
the hunk is never applied silently or in the wrong place.

**A proposed passage is found as the model copied it.** A model copying a
passage straightens a curly quote, drops the backticks around a name or joins
two lines; the passage is then looked for with those differences evened out on
both sides, and the hunk keeps the draft's own characters. It must still occur
exactly once - evening out never decides between two places.

**Undo is anchored the same way**, on what Accept wrote: a person who edited the
accepted text by hand has made a newer decision, and Undo refuses to reverse it.

**A tool hunk compares the binding with what it read.** The name and
description overrides the proposal was computed against must still be the
draft's, or a newer manual edit would be overwritten. A field hunk does the same
with the value it read, through :mod:`app.services.authoring_fields`.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.agents.capabilities import ToolOverride
from app.agents.spec import AgentSpec
from app.db.models.authoring import HunkKind, HunkStatus, SpecProposalHunk
from app.schemas.authoring import InstructionChange, Rejection
from app.services import authoring_fields

CONTEXT_CHARS = 60
"""How much surrounding text an anchor keeps on either side."""


@dataclass(frozen=True)
class Anchor:
    """Where an instructions passage sat, and what surrounded it.

    An empty `before` means the passage started the text; an empty `after`,
    that it ended it.
    """

    old_text: str
    before: str
    after: str


_SAME = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00a0": " ",
    }
)
_SPACE = re.compile(r"\s+")


def _evened(text: str) -> tuple[str, list[int]]:
    """`text` as compared loosely, and where each of its characters came from.

    Quotes and dashes become plain, backticks go, and every run of whitespace is
    one space; `positions[i]` is the index in `text` of the evened character `i`.
    """
    characters: list[str] = []
    positions: list[int] = []
    for index, character in enumerate(text.translate(_SAME)):
        if character == "`":
            continue
        if _SPACE.fullmatch(character):
            if characters and characters[-1] == " ":
                continue
            character = " "
        characters.append(character)
        positions.append(index)
    return "".join(characters), positions


def _place(text: str, passage: str) -> tuple[int, int] | Rejection:
    """Where `passage` sits in `text`, as `(start, end)` in `text`'s own characters."""
    exact = _occurrences(text, passage)
    if len(exact) == 1:
        return exact[0], exact[0] + len(passage)
    if exact:
        return Rejection.AMBIGUOUS_ANCHOR
    evened, positions = _evened(text)
    needle, _ = _evened(passage)
    needle = needle.strip()
    found = _occurrences(evened, needle) if needle else []
    if len(found) > 1:
        return Rejection.AMBIGUOUS_ANCHOR
    if not found:
        return Rejection.UNANCHORED
    return positions[found[0]], positions[found[0] + len(needle) - 1] + 1


def evened(text: str) -> str:
    """`text` as `mentions` compares it, for checking many passages against one text."""
    return _evened(text)[0]


def mentioned(evened_text: str, passage: str) -> bool:
    """Whether `passage` occurs in a text already put through :func:`evened`."""
    needle = _evened(passage)[0].strip()
    return bool(needle) and needle in evened_text


def mentions(text: str, passage: str) -> bool:
    """Whether `passage` occurs in `text`, compared as loosely as an anchor is."""
    return mentioned(evened(text), passage)


def _occurrences(text: str, needle: str) -> list[int]:
    found: list[int] = []
    start = text.find(needle)
    while start != -1:
        found.append(start)
        start = text.find(needle, start + 1)
    return found


def anchor_change(base: str, change: InstructionChange) -> dict[str, Any] | Rejection:
    """The hunk columns for a change to `base`, or why it cannot be anchored.

    A replaced passage must occur exactly once; an insertion follows a passage
    that occurs exactly once, or ends the text. A change that changes nothing
    is not a change. The hunk holds the passage as `base` has it, so applying it
    later finds the draft's own characters.
    """
    if change.old_text == change.new_text:
        return Rejection.NO_CHANGE
    if change.old_text:
        placed = _place(base, change.old_text)
        if isinstance(placed, Rejection):
            return placed
        start, end = placed
    elif change.after:
        placed = _place(base, change.after)
        if isinstance(placed, Rejection):
            return placed
        start = end = placed[1]
    else:
        start = end = len(base)
    if base[start:end] == change.new_text:
        return Rejection.NO_CHANGE
    return {
        "base_start": start,
        "base_end": end,
        "context_before": base[max(0, start - CONTEXT_CHARS) : start],
        "context_after": base[end : end + CONTEXT_CHARS],
        "old_text": base[start:end],
        "new_text": change.new_text,
    }


def locate(text: str, anchor: Anchor) -> int | None:
    """Where `anchor`'s passage starts in `text`, or `None` when it does not resolve."""

    def surrounded(position: int) -> bool:
        end = position + len(anchor.old_text)
        before = text[:position].endswith(anchor.before) if anchor.before else position == 0
        after = text[end:].startswith(anchor.after) if anchor.after else end == len(text)
        return before and after

    if anchor.old_text:
        positions = _occurrences(text, anchor.old_text)
        exact = [position for position in positions if surrounded(position)]
        if len(exact) == 1:
            return exact[0]
        return positions[0] if len(positions) == 1 else None
    candidates = (
        [p + len(anchor.before) for p in _occurrences(text, anchor.before)]
        if anchor.before
        else [0]
    )
    exact = [position for position in candidates if surrounded(position)]
    return exact[0] if len(exact) == 1 else None


def _proposed(hunk: SpecProposalHunk) -> Anchor:
    return Anchor(hunk.old_text, hunk.context_before, hunk.context_after)


def _accepted(hunk: SpecProposalHunk) -> Anchor:
    return Anchor(hunk.accepted_text or "", hunk.context_before, hunk.context_after)


def apply_text(text: str, hunk: SpecProposalHunk, replacement: str) -> str | None:
    """`text` with the hunk's passage replaced by `replacement`, or `None` when stale."""
    position = locate(text, _proposed(hunk))
    if position is None:
        return None
    return text[:position] + replacement + text[position + len(hunk.old_text) :]


def undo_text(text: str, hunk: SpecProposalHunk) -> str | None:
    """`text` with what Accept wrote put back as it was, or `None` when that no longer stands."""
    accepted = _accepted(hunk)
    position = locate(text, accepted)
    if position is None:
        return None
    return text[:position] + hunk.old_text + text[position + len(accepted.old_text) :]


def current_override(
    spec: AgentSpec, capability_id: str, tool_id: str
) -> tuple[int | None, str | None, str | None]:
    """Where the capability is bound, and the tool's name and description overrides.

    The index is `None` when the draft does not bind the capability at all.
    """
    for index, binding in enumerate(spec.capabilities):
        if binding.id == capability_id:
            override = binding.tool_overrides.get(tool_id)
            if override is None:
                return index, None, None
            return index, override.name, override.description
    return None, None, None


def _with_override(
    spec: AgentSpec, index: int, tool_id: str, override: ToolOverride | None
) -> AgentSpec:
    binding = spec.capabilities[index]
    overrides = dict(binding.tool_overrides)
    if override is None:
        overrides.pop(tool_id, None)
    else:
        overrides[tool_id] = override
    capabilities = list(spec.capabilities)
    capabilities[index] = binding.model_copy(update={"tool_overrides": overrides})
    return spec.model_copy(update={"capabilities": capabilities})


def apply_tool(spec: AgentSpec, hunk: SpecProposalHunk) -> tuple[AgentSpec, dict[str, str]] | None:
    """`spec` with the hunk's override written, and that override - or `None` when stale."""
    tool_id = hunk.tool_id or ""
    index, name, description = current_override(spec, hunk.capability_id or "", tool_id)
    if index is None or (name, description) != (hunk.base_name, hunk.base_description):
        return None
    override = ToolOverride(
        name=hunk.new_name if hunk.new_name is not None else name,
        description=hunk.new_description if hunk.new_description is not None else description,
    )
    return _with_override(spec, index, tool_id, override), override.model_dump(exclude_none=True)


def undo_tool(spec: AgentSpec, hunk: SpecProposalHunk) -> AgentSpec | None:
    """`spec` with the tool's override as the proposal found it, or `None` when it moved since."""
    tool_id = hunk.tool_id or ""
    index, name, description = current_override(spec, hunk.capability_id or "", tool_id)
    accepted = hunk.accepted_override or {}
    if index is None or (name, description) != (accepted.get("name"), accepted.get("description")):
        return None
    if hunk.base_name is None and hunk.base_description is None:
        return _with_override(spec, index, tool_id, None)
    return _with_override(
        spec, index, tool_id, ToolOverride(name=hunk.base_name, description=hunk.base_description)
    )


def apply_field(spec: AgentSpec, hunk: SpecProposalHunk, value: Any) -> AgentSpec | None:
    """`spec` with a field hunk's change made with `value`, or `None` when it is stale."""
    path, op = hunk.path or "", hunk.op or ""
    accepted = authoring_fields.as_accepted(path, op, value)
    return authoring_fields.apply(spec, path, op, hunk.base_value, accepted)


def undo_field(spec: AgentSpec, hunk: SpecProposalHunk) -> AgentSpec | None:
    """`spec` with an accepted field hunk reversed, or `None` when it was edited since."""
    return authoring_fields.undo(
        spec, hunk.path or "", hunk.op or "", hunk.base_value, hunk.accepted_value
    )


def apply(spec: AgentSpec, hunk: SpecProposalHunk, *, text: str | None = None) -> AgentSpec | None:
    """`spec` with one pending hunk applied, or `None` when it is stale.

    `text` replaces an instructions hunk's proposed text - the person's edit of it.
    """
    if hunk.kind == HunkKind.SPEC_FIELD.value:
        return apply_field(spec, hunk, hunk.new_value)
    if hunk.kind == HunkKind.TOOL_OVERRIDE.value:
        applied = apply_tool(spec, hunk)
        return None if applied is None else applied[0]
    instructions = apply_text(spec.instructions, hunk, hunk.new_text if text is None else text)
    return None if instructions is None else spec.model_copy(update={"instructions": instructions})


def applies(spec: AgentSpec, hunk: SpecProposalHunk) -> bool:
    """Whether a pending hunk still applies, or an accepted one can still be undone."""
    if hunk.status == HunkStatus.ACCEPTED.value:
        if hunk.kind == HunkKind.SPEC_FIELD.value:
            return undo_field(spec, hunk) is not None
        if hunk.kind == HunkKind.TOOL_OVERRIDE.value:
            return undo_tool(spec, hunk) is not None
        return undo_text(spec.instructions, hunk) is not None
    if hunk.status == HunkStatus.PENDING.value:
        return apply(spec, hunk) is not None
    return False


def projection(
    spec: AgentSpec, hunks: Sequence[SpecProposalHunk]
) -> tuple[AgentSpec, list[SpecProposalHunk]]:
    """The draft as it would be with every pending hunk accepted, and the hunks left out.

    Hunks apply in order, each to the result of the last; one that no longer
    resolves - stale on the draft, or overlapping one applied before it - is
    left out rather than guessed at.
    """
    projected = spec
    skipped: list[SpecProposalHunk] = []
    for hunk in hunks:
        if hunk.status != HunkStatus.PENDING.value:
            continue
        applied = apply(projected, hunk)
        if applied is None:
            skipped.append(hunk)
            continue
        projected = applied
    return projected, skipped
