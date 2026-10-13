"""Knowledge gaps: the questions a knowledge base could not answer, grouped into topics.

Agents record every knowledge search they make (see
`app.agents.capabilities.knowledge`). A search that returned nothing, or nothing
as similar to the query as `KNOWLEDGE_GAP_MIN_SIMILARITY`, is a *miss*. Misses
are grouped per knowledge base by the meaning of the query, in that
collection's own embedding space, into topics a person can act on: add the
missing document, or turn the questions into dataset cases to check it.

Grouping embeds queries but asks no model to write anything, so it runs for
every organization, like ingestion embeddings do. Nothing here ever adds a
document to a collection.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID

import numpy as np
import numpy.typing as npt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.knowledge_gap import KnowledgeGapTopic, KnowledgeSearch
from app.repositories import knowledge_base_repo, knowledge_gap_repo
from app.services.embedding_resolution import ResolvedEmbeddings, embeddings_for_collection
from app.services.rag.vectorstore import embedder_for

logger = logging.getLogger(__name__)

TOPIC_SIMILARITY = 0.80
"""How similar a miss must be to a topic's centroid to join it, rather than start one."""

GROUPING_BATCH = 500
"""The most misses one knowledge base embeds in one pass; the rest wait for the next."""

Vector = npt.NDArray[np.float64]


def _unit(values: list[float]) -> Vector:
    vector = np.asarray(values, dtype=np.float64)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


@dataclass
class _Cluster:
    """A topic while a pass assigns to it: the stored row, or one still to be created."""

    centroid: Vector
    size: int
    topic: KnowledgeGapTopic | None
    searches: list[UUID]
    moved: bool = False

    def take(self, vector: Vector, search_id: UUID) -> None:
        self.centroid = (self.centroid * self.size + vector) / (self.size + 1)
        self.size += 1
        self.searches.append(search_id)
        self.moved = True


def _assign(
    misses: list[tuple[UUID, Vector]], clusters: list[_Cluster], *, threshold: float
) -> list[_Cluster]:
    """Put each miss into the nearest cluster at least `threshold` similar, or a new one.

    In order, so a miss can join a cluster an earlier miss of the same pass
    started. Vectors are unit length; a centroid is compared by direction.
    """
    for search_id, vector in misses:
        best: _Cluster | None = None
        if clusters:
            directions = np.vstack([_unit(c.centroid.tolist()) for c in clusters])
            scores = directions @ vector
            index = int(np.argmax(scores))
            if float(scores[index]) >= threshold:
                best = clusters[index]
        if best is None:
            clusters.append(
                _Cluster(centroid=vector, size=1, topic=None, searches=[search_id], moved=True)
            )
        else:
            best.take(vector, search_id)
    return clusters


class KnowledgeGapService:
    """Finds, groups and reports what agents could not find in their knowledge bases."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def waiting_to_be_grouped(self) -> list[tuple[UUID, UUID]]:
        """Every `(organization, knowledge base)` with a miss no topic has taken yet."""
        return await knowledge_gap_repo.knowledge_bases_with_ungrouped_misses(
            self.db, threshold=settings.KNOWLEDGE_GAP_MIN_SIMILARITY
        )

    async def forget_empty_topics(self) -> int:
        """Remove the topics left with no searches, across the deployment."""
        return await knowledge_gap_repo.delete_empty_topics(self.db)

    async def group_pending(self, *, organization_id: UUID, knowledge_base_id: UUID) -> int:
        """Group up to :data:`GROUPING_BATCH` of a knowledge base's ungrouped misses.

        A knowledge base with no misses waiting costs a query and no embedding
        call. One whose embedding credential cannot be resolved is left as it
        is, and its misses wait for a pass that can embed them.

        Returns:
            How many misses were placed in a topic.
        """
        misses = await knowledge_gap_repo.ungrouped_misses(
            self.db,
            knowledge_base_id,
            organization_id=organization_id,
            threshold=settings.KNOWLEDGE_GAP_MIN_SIMILARITY,
            limit=GROUPING_BATCH,
        )
        if not misses:
            return 0
        kb = await knowledge_base_repo.get_by_id(self.db, knowledge_base_id)
        if kb is None or kb.organization_id != organization_id:
            return 0
        resolved = await embeddings_for_collection(kb.collection_name, organization_id)
        if resolved is None:
            logger.warning(
                "knowledge_gaps_not_grouped",
                extra={"knowledge_base_id": str(kb.id), "reason": "no embedding configuration"},
            )
            return 0

        vectors = await self._embed(kb.collection_name, resolved, misses)
        stored = await knowledge_gap_repo.topics_in_space(
            self.db,
            kb.id,
            organization_id=organization_id,
            embedding_model=kb.embedding_model,
        )
        clusters = _assign(
            [(search.id, vectors[search.query]) for search in misses],
            [
                _Cluster(
                    centroid=np.asarray(topic.centroid, dtype=np.float64),
                    size=max(size, 1),
                    topic=topic,
                    searches=[],
                )
                for topic, size in stored
            ],
            threshold=TOPIC_SIMILARITY,
        )

        placements: list[tuple[UUID, UUID]] = []
        for cluster in clusters:
            if not cluster.moved:
                continue
            centroid = cluster.centroid.tolist()
            if cluster.topic is None:
                topic = await knowledge_gap_repo.create_topic(
                    self.db,
                    organization_id=organization_id,
                    knowledge_base_id=kb.id,
                    centroid=centroid,
                    embedding_model=kb.embedding_model,
                )
            else:
                topic = await knowledge_gap_repo.update_topic(
                    self.db, topic=cluster.topic, update_data={"centroid": centroid}
                )
            placements.extend((topic.id, search_id) for search_id in cluster.searches)
        await knowledge_gap_repo.add_members(self.db, placements)
        return len(placements)

    @staticmethod
    async def _embed(
        collection_name: str, resolved: ResolvedEmbeddings, misses: list[KnowledgeSearch]
    ) -> dict[str, Vector]:
        """Each distinct query once, in one request, off the event loop."""
        embedder = embedder_for(collection_name, resolved)
        queries = list(dict.fromkeys(search.query for search in misses))
        embedded = await asyncio.to_thread(embedder.embed_queries, queries)
        return {query: _unit(vector) for query, vector in zip(queries, embedded, strict=True)}
