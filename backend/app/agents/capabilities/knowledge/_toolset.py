"""The tools the knowledge capability exposes."""

from __future__ import annotations

import logging
from datetime import date

from pydantic import ValidationError
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._failures import steer
from app.agents.capabilities.knowledge._search import search_knowledge_base
from app.agents.deps import AgentDeps
from app.services.rag.filters import DocumentType, RetrievalFilters, Source

logger = logging.getLogger(__name__)


def _normalize(value: list[str] | None) -> list[str] | None:
    """Map an empty list to None at the tool boundary (FA-039 §2.1).

    A model that emits `[]` for a list it means to leave unfiltered is expressing
    a correct not-filtering intent, so it becomes `None` rather than tripping the
    empty-list validation into a needless retry. (`extra="forbid"` is not the
    tool's guard - the typed signature is; the smuggled-key rejection lives on
    the API route.)
    """
    return value or None


def build_knowledge_toolset(*, default_top_k: int) -> FunctionToolset[AgentDeps]:
    """A toolset with one search tool, under the name it is declared with.

    The same search is "Search orders" for one agent and "Look up policies" for
    another - but that is said in the binding's `tool_overrides`, applied for
    every capability at once, not here. A rename this toolset performed itself
    would be invisible to the approval gate.
    """

    async def search_documents(
        ctx: RunContext[AgentDeps],
        query: str,
        top_k: int | None = None,
        source: list[Source] | None = None,
        document_type: list[DocumentType] | None = None,
        organizational_unit: list[str] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> str:
        """Search the organization's documents for passages relevant to a question.

        Use before answering anything that depends on internal knowledge, and
        cite the document names from the results rather than paraphrasing.

        The optional filters narrow the search; they can only narrow it, never
        widen it, and none of them can reach another organization's documents.

        Args:
            query: What to look for, phrased as the user would ask it.
            top_k: How many passages to return. Omit to use the agent's default.
            source: Restrict to these ingestion origins (upload, local, gdrive, s3).
            document_type: Restrict to these document types (file extensions, e.g.
                "pdf", "docx"). Choose from the closed set the schema lists.
            organizational_unit: Restrict to these organizational-unit tags.
            date_from: Only documents dated on or after this date (YYYY-MM-DD).
            date_to: Only documents dated on or before this date (YYYY-MM-DD).

        Returns:
            Formatted passages with their source documents and relevance scores.
        """
        try:
            filters = RetrievalFilters(
                # A model's `[]` means "not filtering this"; normalize it away
                # before validation so it is not read as an empty allow-list.
                source=_normalize([str(s) for s in source] if source else None),
                document_type=_normalize(
                    [str(d) for d in document_type] if document_type else None
                ),
                organizational_unit=_normalize(organizational_unit),
                date_from=date_from,
                date_to=date_to,
            )
        except ValidationError as exc:
            # A corrected-call steer, not an outage: an unknown document_type or a
            # reversed date range is something the model can fix on the next
            # attempt, so it must not land in the broad "unavailable" handler
            # below (which reads as "the knowledge base is down", untrue and
            # unactionable). The field messages tell the model what to change.
            logger.info("knowledge_search_invalid_filter")
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or 'filters'}: {err['msg']}"
                for err in exc.errors()
            )
            return steer(ctx, f"Those search filters are not valid: {problems}. Adjust and retry.")

        try:
            return await search_knowledge_base(
                query=query,
                # Resolved server-side from the agent's bound collections. The
                # model chooses *what* to search, never *where*.
                kb_collection_names=ctx.deps.kb_collection_names,
                top_k=top_k or default_top_k,
                # Builds the security-bearing tenant scope, so a shared collection
                # name returns and embeds only this organization's chunks (#913).
                organization_id=ctx.deps.organization_id,
                filters=filters,
            )
        except Exception:
            # A retry rather than a returned message: an error in the shape of a
            # result reads as "nothing found", and the model then answers from
            # memory - confidently, and without saying it had to.
            logger.exception("knowledge_search_failed")
            return steer(ctx, "Knowledge base temporarily unavailable, please try again.")

    toolset: FunctionToolset[AgentDeps] = FunctionToolset()
    toolset.add_function(search_documents, takes_ctx=True)
    return toolset
