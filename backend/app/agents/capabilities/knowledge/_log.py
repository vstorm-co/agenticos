"""What a run's knowledge searches found, kept for the run's terminal write."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.schemas.knowledge_gap import KnowledgeSearchRecord
from app.services.rag.models import SearchResult

KNOWLEDGE_SEARCH_LOG_RESOURCE = "knowledge_search_log"

MAX_QUERY_CHARS = 1_000
"""How much of a query is kept: enough to group and read it, bounded for the embedding batch."""

MAX_FOUND = 3
"""How many passages one search keeps for a reader of what a run found."""

MAX_FOUND_CHARS = 300
"""How much of a passage is kept: enough to see what it said, bounded in a stored result."""


@dataclass(frozen=True)
class FoundPassage:
    """A passage a search returned, as whoever reads the run's result is shown it.

    Attributes:
        source: The document it came from, by file name, when the store knows it.
        quote: The start of the matched passage.
    """

    source: str | None
    quote: str


@dataclass
class KnowledgeSearchLog:
    """The searches one run made, in the order it made them.

    Filled by the search tool and written by the runner when the run ends, so
    the tool never touches the run's database session, which concurrent tool
    calls share. A delegate gets a view of the same list under its own agent and
    collections through :meth:`for_agent`.

    Attributes:
        agent_id: The agent the searches are attributed to.
        collections: The agent's bound collections, vector-store name to the
            knowledge base ids a search of it reads. A name outside it is not
            recorded.
        records: What has been searched so far, shared by every view.
        found: Where a run's caller keeps the passages its searches returned, the
            best few of each; `None` keeps none.
    """

    agent_id: UUID
    collections: Mapping[str, tuple[UUID, ...]]
    records: list[KnowledgeSearchRecord] = field(default_factory=list)
    found: list[FoundPassage] | None = None

    def for_agent(
        self, agent_id: UUID | None, collections: Mapping[str, tuple[UUID, ...]]
    ) -> KnowledgeSearchLog:
        """A view for a delegate; one with no agent of its own searches as this one."""
        return KnowledgeSearchLog(
            agent_id=agent_id or self.agent_id,
            collections=collections,
            records=self.records,
            found=self.found,
        )

    def record(
        self, query: str, collection_names: Sequence[str], results: Sequence[SearchResult]
    ) -> None:
        """Keep one search and the best similarity among what it returned."""
        knowledge_base_ids = tuple(
            base_id for name in collection_names for base_id in self.collections.get(name, ())
        )
        if not knowledge_base_ids:
            return
        if self.found is not None:
            self.found.extend(
                FoundPassage(
                    source=result.metadata.get("filename"),
                    quote=" ".join(result.content.split())[:MAX_FOUND_CHARS],
                )
                for result in results[:MAX_FOUND]
            )
        similarities = [r.similarity for r in results if r.similarity is not None]
        self.records.append(
            KnowledgeSearchRecord(
                agent_id=self.agent_id,
                knowledge_base_ids=knowledge_base_ids,
                query=query[:MAX_QUERY_CHARS],
                result_count=len(results),
                top_similarity=max(similarities, default=None),
            )
        )
