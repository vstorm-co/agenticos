"""The tools the knowledge capability exposes."""

from __future__ import annotations

import logging
from datetime import date

from pydantic import ValidationError
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import (
    FallbackExceptionGroup,
    ModelAPIError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.models import Model
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import UsageLimits

from app.agents.capabilities._failures import steer
from app.agents.capabilities._metered import MeteredModel
from app.agents.capabilities.budget import BudgetExceeded, assert_ambient_budget
from app.agents.capabilities.knowledge._search import (
    organizational_units_in_scope,
    search_knowledge_base,
)
from app.agents.capabilities.knowledge._self_query import (
    describe_filters,
    has_any_filter,
    infer_filters_from_query,
)
from app.agents.deps import AgentDeps
from app.agents.observability import inherited_instrumentation
from app.services.rag.filters import DocumentType, RetrievalFilters, Source
from app.services.rag.models import ParentContextMode
from app.services.rag.query_analysis import GenerateText, QueryAnalysisMode, QueryExpansionFailed

logger = logging.getLogger(__name__)

# A retry rather than a returned message: an error in the shape of a result reads
# as "nothing found", and the model then answers from memory - confidently, and
# without saying it had to.
_UNAVAILABLE = "Knowledge base temporarily unavailable, please try again."
# The expansion agent has no tools and a plain-text output, so it makes one
# request - and a second only when Pydantic AI asks again for an empty answer,
# which is its default single output retry. Anything past that is a misbehaving
# model, and the expansion gives up rather than spending more on it.
_EXPANSION_LIMITS = UsageLimits(request_limit=2)

# What an expansion call is expected to fail with: the provider refused or was
# unreachable (a `FallbackModel` gathers its members' refusals into a group), the
# model answered with nothing usable, the call hit its own limit, or the run's
# budget is spent. Each makes the search fall back to the plain query; anything
# else is a bug and propagates.
_EXPECTED_EXPANSION_FAILURES = (
    ModelAPIError,
    FallbackExceptionGroup,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
    BudgetExceeded,
)


def _model_generate(ctx: RunContext[AgentDeps]) -> GenerateText | None:
    """A metered one-prompt caller over the run's own model, for query expansion.

    Expansion inherits `ctx.model` - the model whose credential was resolved from
    the vault - rather than a model named in config, which on this platform would
    be looked up against process environment variables (compaction and the LLM
    system reminder make the same choice, for the same reason).

    The nested call runs on its own usage, not the host run's: the host's request
    wrapper never sees it, so `MeteredModel` books each response to the run's
    ledger itself, once, whatever else is in flight - two parallel searches each
    book exactly what they spent. The budget is checked before every call, since
    the host guard only refuses the host's *next* request.

    Returns `None` for a realtime model, which cannot serve a request-response
    call; `plan_queries` then degrades to the plain query.
    """
    model = ctx.model
    if not isinstance(model, Model):
        return None
    # Traced as the host run is traced - its Logfire project and its content
    # setting - or the prompt built from the user's question leaves through the
    # global, content-on default.
    agent: Agent[None, str] = Agent(MeteredModel(model), output_type=str)
    agent.instrument = inherited_instrumentation(ctx.agent)

    async def generate(prompt: str) -> str:
        try:
            await assert_ambient_budget()
            result = await agent.run(prompt, usage_limits=_EXPANSION_LIMITS)
        except _EXPECTED_EXPANSION_FAILURES as exc:
            raise QueryExpansionFailed(type(exc).__name__) from exc
        return result.output

    return generate


def _normalize(value: list[str] | None) -> list[str] | None:
    """Map an empty list to None at the tool boundary (FA-039 §2.1).

    A model that emits `[]` for a list it means to leave unfiltered is expressing
    a correct not-filtering intent, so it becomes `None` rather than tripping the
    empty-list validation into a needless retry. (`extra="forbid"` is not the
    tool's guard - the typed signature is; the smuggled-key rejection lives on
    the API route.)
    """
    return value or None


def build_knowledge_toolset(
    *,
    default_top_k: int,
    self_query_enabled: bool = False,
    query_analysis_mode: QueryAnalysisMode = "off",
    query_analysis_max_variants: int = 3,
    parent_context: ParentContextMode = ParentContextMode.OFF,
) -> FunctionToolset[AgentDeps]:
    """A toolset with one search tool, under the name it is declared with.

    The same search is "Search orders" for one agent and "Look up policies" for
    another - but that is said in the binding's `tool_overrides`, applied for
    every capability at once, not here. A rename this toolset performed itself
    would be invisible to the approval gate.

    With `self_query_enabled`, a search the model runs without naming any filter
    of its own first asks an LLM to derive the FA-039 business filters the query
    implies (`_self_query.infer_filters_from_query`). The model's explicit filters
    win when it supplies them, and `infer_filters=False` skips the inference. The
    result names what was inferred on its first line, so the model can see why a
    search came back narrow and repeat it without. An empty or failed inference
    falls back to an unfiltered - but still tenant/collection-scoped - search.

    `query_analysis_mode` optionally expands the query before retrieval (#1649):
    the expansion runs through the host run's model and every produced query is
    retrieved under the same scope and filters as the original.
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
        infer_filters: bool = True,
    ) -> str:
        """Search the organization's documents for passages relevant to a question.

        Use before answering anything that depends on internal knowledge, and
        cite the document names from the results rather than paraphrasing.

        The optional filters narrow the search; they can only narrow it, never
        widen it, and none of them can reach another organization's documents.

        If this agent infers filters, a call that passes none of them may have
        filters inferred from the query ("pdfs from last month" becomes a
        document type and a date range). The result then starts with a line
        naming them. If they narrowed too far, search again with
        `infer_filters` false.

        Args:
            query: What to look for, phrased as the user would ask it.
            top_k: How many passages to return. Omit to use the agent's default.
            source: Restrict to these ingestion origins (upload, local, gdrive, s3).
            document_type: Restrict to these document types (file extensions, e.g.
                "pdf", "docx"). Choose from the closed set the schema lists.
            organizational_unit: Restrict to these organizational-unit tags.
            date_from: Only documents dated on or after this date (YYYY-MM-DD).
            date_to: Only documents dated on or before this date (YYYY-MM-DD).
            infer_filters: Whether filters may be inferred from the query when you
                pass none. Set false to search the query as written.

        Returns:
            Formatted passages with their source documents and relevance scores,
            preceded by a line naming any filters inferred from the query.
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

        notice = ""
        if self_query_enabled and infer_filters and not has_any_filter(filters):
            # Only when the model named no filter itself - its explicit intent
            # wins. The inferred object is a `RetrievalFilters`, so it carries no
            # tenant or authorization field and runs through the same validation;
            # a `None` result leaves the search unfiltered within the still-enforced
            # scope, never widened.
            try:
                units = await organizational_units_in_scope(
                    ctx.deps.kb_collection_names, ctx.deps.organization_id
                )
            except Exception:
                logger.exception("knowledge_facet_lookup_failed")
                return steer(ctx, _UNAVAILABLE)
            # Outside any broad `except`: `BudgetExceeded` and a defect in the
            # inference must reach the runner, not read as an unavailable search.
            inferred = await infer_filters_from_query(
                ctx.model,
                query,
                organizational_units=units,
                instrument=inherited_instrumentation(ctx.agent),
            )
            if inferred is not None:
                filters = inferred
                notice = (
                    f"Filters inferred from the question: {describe_filters(inferred)}. "
                    "To search without them, call again with infer_filters=false.\n\n"
                )

        # Built only when a mode will call the model, so `off` never constructs
        # one. `plan_queries` degrades to the plain query if this is None.
        generate = _model_generate(ctx) if query_analysis_mode != "off" else None
        try:
            return notice + await search_knowledge_base(
                query=query,
                # Resolved server-side from the agent's bound collections. The
                # model chooses *what* to search, never *where*.
                kb_collection_names=ctx.deps.kb_collection_names,
                top_k=top_k or default_top_k,
                # Builds the security-bearing tenant scope, so a shared collection
                # name returns and embeds only this organization's chunks (#913).
                organization_id=ctx.deps.organization_id,
                filters=filters,
                analysis_mode=query_analysis_mode,
                analysis_max_variants=query_analysis_max_variants,
                generate=generate,
                # The agent's configured small-to-big mode. Return-path only:
                # matching still runs on the small chunks (#1651).
                parent_context=parent_context,
            )
        except Exception:
            logger.exception("knowledge_search_failed")
            return steer(ctx, _UNAVAILABLE)

    toolset: FunctionToolset[AgentDeps] = FunctionToolset()
    toolset.add_function(search_documents, takes_ctx=True)
    return toolset
