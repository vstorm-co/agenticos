"""Parent-document (small-to-big) retrieval: surrounding context for matched chunks (#1651).

Matching and ranking run on the precise small chunks and are not touched here.
After they have picked the results, each result can be returned with the text
around it - its neighbouring chunks (`window`), or as much of the rest of its
document as the budget allows, nearest first (`parent`) - so the model reads a
passage while the citation and the score stay the matched chunk's.

Three rules decide what a result gets:

- **The matched chunk is never shortened.** Only the context added around it is
  charged against the budgets, so switching the mode on can never make the model
  read less than it would with the mode off. A result nothing could be added to
  keeps `expanded_content = None` and reads exactly as before.
- **A passage is contiguous.** It grows outward from the match and a direction
  closes at the first chunk that does not fit or was already returned with an
  earlier result, so text that was not adjacent in the document is never joined
  as if it were.
- **The read is bounded.** The chunks around a match are read by position -
  `WINDOW_CHUNKS` or `PARENT_CHUNKS_EACH_SIDE` on each side - never the whole
  document, so a result from a very large upload costs a bounded read.

The limits are constants rather than settings: nothing configures `RAGSettings`
per deployment any more, and a knob that reads as configurable and is not is worse
than a stated number.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from app.services.rag.filters import AppScope, RetrievalScope, TenantScope
from app.services.rag.models import DocumentChunk, ParentContextMode, SearchResult

#: Neighbouring chunks read on each side of a match in `window` mode.
WINDOW_CHUNKS = 1
#: Chunks read on each side of a match in `parent` mode - the bound on the read,
#: well past what the character budget below lets through for ordinary chunks.
PARENT_CHUNKS_EACH_SIDE = 64
#: Characters of added context one result may carry, beyond its own matched chunk.
MAX_ADDED_CHARS_PER_RESULT = 8000
#: Characters of added context across every result one search returns.
MAX_ADDED_CHARS_PER_TURN = 24000

_SEP = "\n\n"


class ChunkReader(Protocol):
    """The one store read expansion needs: the chunks around a position in a document."""

    async def get_chunks_around(
        self,
        collection_name: str,
        document_id: str,
        tenant: UUID | None,
        *,
        page_num: int,
        chunk_num: int,
        before: int,
        after: int,
    ) -> list[DocumentChunk]: ...


#: Which collection a result's siblings are read from, and under which tenant -
#: or `None` when this result is not to be expanded.
FetchResolver = Callable[[SearchResult], tuple[str, UUID | None] | None]


def expansion_tenant(scope: RetrievalScope) -> tuple[bool, UUID | None]:
    """Whether a search under `scope` may be expanded, and the tenant it reads under.

    Siblings are read under exactly the tenant the match was found under: a
    `TenantScope`'s organization, or `None` - the untagged, deployment-wide rows -
    for an `AppScope`. An `UnscopedScope` (a maintenance search with no tenant
    conjunct) is not expanded at all: it can match any tenant's rows, and no
    caller that asks for expansion searches that way.
    """
    if isinstance(scope, TenantScope):
        return True, scope.organization_id
    if isinstance(scope, AppScope):
        return True, None
    return False, None


def assemble_passage(
    chunks: list[DocumentChunk],
    match_pos: int,
    parent_doc_id: str,
    emitted: set[tuple[str, int, int]],
    budget: int,
) -> tuple[str, int] | None:
    """The match with as much contiguous context as `budget` allows, and what was added.

    Returns `(passage, added_chars)`, or `None` when no neighbour could be added -
    the caller then leaves the result unexpanded. `emitted` holds the
    `(parent_doc_id, page_num, chunk_num)` of every chunk already returned this
    search; it is updated with what this passage keeps.
    """
    kept = {match_pos}
    added = 0
    left, right = match_pos - 1, match_pos + 1
    left_open = right_open = True

    def fits(pos: int) -> bool:
        chunk = chunks[pos]
        if (parent_doc_id, chunk.page_num, chunk.chunk_num) in emitted:
            return False
        return added + len(_SEP) + len(chunk.content) <= budget

    while left_open or right_open:
        if left_open:
            if left >= 0 and fits(left):
                kept.add(left)
                added += len(_SEP) + len(chunks[left].content)
                left -= 1
            else:
                left_open = False
        if right_open:
            if right < len(chunks) and fits(right):
                kept.add(right)
                added += len(_SEP) + len(chunks[right].content)
                right += 1
            else:
                right_open = False

    if len(kept) == 1:
        return None
    ordered = [chunks[pos] for pos in sorted(kept)]
    for chunk in ordered:
        emitted.add((parent_doc_id, chunk.page_num, chunk.chunk_num))
    return _SEP.join(chunk.content for chunk in ordered), added


async def expand_context(
    store: ChunkReader,
    results: list[SearchResult],
    mode: ParentContextMode,
    resolve_fetch: FetchResolver,
) -> None:
    """Attach surrounding context to each result, in place, within the budgets.

    One budget spans every result passed in, so a caller searching several
    collections expands once, after merging, rather than granting each
    collection its own. Results are expanded in rank order until the per-search
    budget is spent.
    """
    if mode is ParentContextMode.OFF:
        return
    each_side = WINDOW_CHUNKS if mode is ParentContextMode.WINDOW else PARENT_CHUNKS_EACH_SIDE
    turn_used = 0
    emitted: set[tuple[str, int, int]] = set()

    for result in results:
        budget = min(MAX_ADDED_CHARS_PER_RESULT, MAX_ADDED_CHARS_PER_TURN - turn_used)
        if budget <= 0:
            break
        # The content-hash dedup fallback leaves a result with no document.
        if not result.parent_doc_id:
            continue
        fetch = resolve_fetch(result)
        if fetch is None:
            continue
        collection_name, tenant = fetch
        page_num = int(result.metadata.get("page_num", 0) or 0)
        chunk_num = int(result.metadata.get("chunk_num", 0) or 0)
        chunks = await store.get_chunks_around(
            collection_name,
            result.parent_doc_id,
            tenant,
            page_num=page_num,
            chunk_num=chunk_num,
            before=each_side,
            after=each_side,
        )
        match_pos = next(
            (
                pos
                for pos, chunk in enumerate(chunks)
                if chunk.page_num == page_num and chunk.chunk_num == chunk_num
            ),
            None,
        )
        # A match whose row is gone by now (a concurrent re-ingest) has nothing
        # to grow from, and is returned as it was matched.
        if match_pos is None:
            continue
        # The match is always in `emitted` once returned, whether or not anything
        # was added to it, so a later result's window does not repeat it.
        emitted.add((result.parent_doc_id, page_num, chunk_num))
        assembled = assemble_passage(chunks, match_pos, result.parent_doc_id, emitted, budget)
        if assembled is None:
            continue
        result.expanded_content, added = assembled
        turn_used += added
