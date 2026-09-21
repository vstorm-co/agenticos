"""Self-query: infer FA-039 business filters from a natural-language query.

An optional, per-agent step. When the agent's knowledge binding turns it on and
the model asked to search without naming any filter itself, an LLM reads the
question ("documents from last month about onboarding") and derives the business
filters it implies (a `date_from`, a `document_type`).

Two properties are load-bearing and both come from typing the inference output as
:class:`RetrievalFilters` - the very model a caller supplies:

- **Validation parity.** The inferred object runs through the same validators as
  any caller-supplied filter - the closed `source`/`document_type` vocabularies,
  the ordered date range, `extra="forbid"` - because it *is* the same model. There
  is no second set of rules to drift.
- **The security invariant (#1593).** `RetrievalFilters` carries no tenant and no
  authorization field and cannot be made to, so the LLM can only ever produce
  business filters. The tenant scope is built server-side in
  :func:`search_knowledge_base` regardless of what comes back here, so self-query
  can only narrow within the caller's scope - never widen it.

Empty or unparsable inference returns `None`, and the caller then searches
unfiltered within the still-enforced tenant/collection scope. No filter is a
narrowing that did not happen, never a widening.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, date, datetime

from pydantic_ai import Agent
from pydantic_ai.models import AbstractModel, Model
from pydantic_ai.usage import RunUsage, UsageLimits

from app.agents.capabilities.budget import record_ambient_usage, usage_counts, usage_delta
from app.services.rag.filters import (
    DOCUMENT_TYPE_VOCABULARY,
    SOURCE_VOCABULARY,
    RetrievalFilters,
)

logger = logging.getLogger(__name__)


def _instructions(today: date) -> str:
    """The extraction prompt, carrying the closed vocabularies the model may use.

    The vocabularies live here rather than in the output schema because the output
    is a plain `RetrievalFilters` (so its validation is identical to a caller's);
    its `source`/`document_type` fields are `list[str]`, so the legal values are
    stated in the prompt and enforced by the model's own validators on the way out.
    """
    sources = ", ".join(sorted(SOURCE_VOCABULARY))
    types = ", ".join(sorted(DOCUMENT_TYPE_VOCABULARY))
    return (
        "You turn a user's document-search query into structured retrieval filters.\n"
        "Return only the filters the query clearly implies, and leave every field "
        "null when it expresses no filter intent. Never invent a filter to be "
        "helpful, and never filter on the query's main topic - that is what the "
        "search itself is for.\n"
        f'Today is {today.isoformat()}; resolve relative dates ("last month", '
        '"this year") against it.\n'
        "Fields:\n"
        f"- source: ingestion origin, one or more of: {sources}.\n"
        f"- document_type: file type/extension, one or more of: {types}.\n"
        "- organizational_unit: organizational-unit tags the query names.\n"
        "- date_from / date_to: inclusive ISO dates (YYYY-MM-DD), date_from on or "
        "before date_to.\n"
        "Only these business filters exist; you cannot select an organization or "
        "otherwise widen access."
    )


def _reserved_limits(limits: UsageLimits | None) -> UsageLimits | None:
    """The run's limits with one request held back for the inference's own call.

    The tool call that triggers inference has already cleared its own request
    check, so a nested run spending the last slot would let that approved call
    push the run one past `request_limit`. Holding a slot back makes the nested run
    raise first; the caller falls back to an unfiltered search, which costs no
    request, and the budget holds.
    """
    if limits is None or limits.request_limit is None:
        return limits
    return replace(limits, request_limit=max(0, limits.request_limit - 1))


def _has_any_filter(filters: RetrievalFilters) -> bool:
    """Whether the model derived any filter at all, or read no intent in the query."""
    return any(
        value is not None
        for value in (
            filters.source,
            filters.document_type,
            filters.organizational_unit,
            filters.date_from,
            filters.date_to,
            filters.parent_doc_id,
        )
    )


async def infer_filters(
    model: AbstractModel,
    query: str,
    *,
    usage: RunUsage,
    usage_limits: UsageLimits | None,
    today: date | None = None,
) -> RetrievalFilters | None:
    """Infer narrowing-only business filters from a natural-language query.

    Reuses the run's own model - the one whose credential the vault resolved - the
    way the LLM reminder and the compaction summary do. Its spend is booked against
    the run's ledger, and it runs under the run's limits minus one reserved request
    so it can never push the run past its own `request_limit`.

    Returns:
        A validated `RetrievalFilters` when the query clearly implies one; `None`
        when it implies none, when the model is not a request-response one, or when
        inference fails for any reason (a provider error, an inferred value the
        model could not correct within its retries, an exhausted reserved budget).
        `None` is the unfiltered fallback - a narrowing that did not happen, never a
        widening, since the tenant/collection scope is enforced by the caller
        regardless.
    """
    if not isinstance(model, Model):
        # A realtime model is not request-response, so it cannot run the inference.
        # Fall back to unfiltered rather than failing the search.
        return None

    agent: Agent[None, RetrievalFilters] = Agent(
        model,
        instructions=_instructions(today or datetime.now(UTC).date()),
        output_type=RetrievalFilters,
    )
    before = usage_counts(usage)
    filters: RetrievalFilters | None = None
    try:
        result = await agent.run(query, usage=usage, usage_limits=_reserved_limits(usage_limits))
        filters = result.output
    except Exception:
        # Any failure falls back to unfiltered search. The invariant holds either
        # way: the scope is server-derived, so no filter is not a widening. An
        # inferred value that fails the shared validation lands here too, after the
        # model's own retries - rejected exactly as a caller's would be, never
        # silently dropped field by field into a partial filter.
        logger.warning("self-query filter inference failed; searching unfiltered", exc_info=True)
    finally:
        spent = usage_delta(before, usage)
        if spent is not None:
            record_ambient_usage(model.model_name or "unknown", spent)

    if filters is None:
        return None
    return filters if _has_any_filter(filters) else None


__all__ = ["infer_filters"]
