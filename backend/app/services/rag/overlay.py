"""Run-owned knowledge drafts, never inserted into a collection or process cache."""

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from app.services.rag.filters import RetrievalQuery, TenantScope
from app.services.rag.models import SearchResult


@dataclass(frozen=True)
class OverlayDocument:
    topic_id: UUID
    organization_id: UUID
    collection_name: str
    title: str
    content: str
    embedding_model: str | None = None
    embedding_dim: int | None = None
    token: UUID = field(default_factory=uuid4)


@dataclass
class KnowledgeOverlay:
    documents: tuple[OverlayDocument, ...]
    returned_topic_ids: set[UUID] = field(default_factory=set)
    failed: bool = False

    def matching(self, collection_name: str, query: RetrievalQuery) -> tuple[OverlayDocument, ...]:
        """Only the exact tenant scope and collection may see a run's draft."""
        if not isinstance(query.scope, TenantScope):
            return ()
        return tuple(
            doc
            for doc in self.documents
            if doc.collection_name == collection_name
            and doc.organization_id == query.scope.organization_id
        )

    def record(self, results: Sequence[SearchResult]) -> None:
        """Credit only drafts actually returned after ranking, filtering and fusion."""
        by_token = {doc.token: doc for doc in self.documents}
        for result in results:
            doc = by_token.get(result.overlay_token) if result.overlay_token is not None else None
            if doc is not None and result.content == doc.content:
                self.returned_topic_ids.add(doc.topic_id)


_ACTIVE: ContextVar[KnowledgeOverlay | None] = ContextVar("knowledge_overlay", default=None)


def active_overlay() -> KnowledgeOverlay | None:
    return _ACTIVE.get()


@contextmanager
def with_overlay(overlay: KnowledgeOverlay | None) -> Generator[None]:
    """Reset on success, failure and cancellation; delegates share their parent's owner."""
    inherited = _ACTIVE.get()
    if inherited is overlay or overlay is None:
        yield
        return
    token = _ACTIVE.set(overlay)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
        overlay.documents = ()
