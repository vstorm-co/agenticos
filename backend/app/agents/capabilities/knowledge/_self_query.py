"""Self-query: infer FA-039 business filters from a natural-language query.

An optional, per-agent step. When the agent's knowledge binding turns it on and
the model asked to search without naming any filter itself, an LLM reads the
question ("pdfs from last month about onboarding") and derives the business
filters it implies: a `source`, a `document_type`, an `organizational_unit` that
exists in the searched collections, a date range.

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

Two fields are held tighter than a caller's. `organizational_unit` is free text,
so an inferred value is kept only when the searched collections actually carry it
- an invented unit would narrow the search to nothing. `parent_doc_id` is never
inferred: a question does not name a vector document id, and a guessed one is a
search of one wrong document.

Empty or failed inference returns `None`, and the caller then searches unfiltered
within the still-enforced tenant/collection scope. No filter is a narrowing that
did not happen, never a widening.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.models import AbstractModel, Model
from pydantic_ai.usage import UsageLimits

from app.agents.capabilities._metered import MeteredModel
from app.agents.capabilities.budget import assert_ambient_budget
from app.services.rag.filters import (
    DOCUMENT_TYPE_VOCABULARY,
    SOURCE_VOCABULARY,
    RetrievalFilters,
)

logger = logging.getLogger(__name__)

_OUTPUT_RETRIES = 1
"""How often the inference may correct an output that failed validation."""

_INFERENCE_LIMITS = UsageLimits(request_limit=_OUTPUT_RETRIES + 1)
"""The nested run's own ceiling: the inference plus each corrected attempt.

The nested run counts on its own usage rather than the host run's `ctx.usage`.
Parallel searches then cannot race for the host run's last request slot, and no
snapshot of a shared counter is diffed - the diff is what booked each of two
concurrent inferences twice. Spend is booked by `MeteredModel` from each response
instead, so the ledger sees every request exactly once.
"""

_MAX_GROUNDED_UNITS = 200
"""The most organizational units stated in the prompt.

The list rides in every inference, so a corpus with more units than this does
not offer `organizational_unit` for inference at all: the model can still name
one explicitly.
"""

_INFERENCE_FAILURES = (ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded)
"""What the nested run may fail with that is no defect of this code.

A provider error or timeout (`ModelAPIError`, `ModelHTTPError` among it), an output
that still failed `RetrievalFilters` validation after its retries
(`UnexpectedModelBehavior`), or the nested run reaching `_INFERENCE_LIMITS`.
Anything else - a bug, `BudgetExceeded`, a cancellation - propagates.
"""


def _instructions(today: date, organizational_units: Sequence[str]) -> str:
    """The extraction prompt, carrying the closed vocabularies the model may use.

    The vocabularies live here rather than in the output schema because the output
    is a plain `RetrievalFilters` (so its validation is identical to a caller's);
    its `source`/`document_type` fields are `list[str]`, so the legal values are
    stated in the prompt and enforced by the model's own validators on the way out.
    `organizational_unit` has no closed vocabulary in code, so the values the
    searched collections carry are stated instead, and :func:`_grounded` drops any
    other.
    """
    sources = ", ".join(sorted(SOURCE_VOCABULARY))
    types = ", ".join(sorted(DOCUMENT_TYPE_VOCABULARY))
    if organizational_units:
        units = (
            "- organizational_unit: organizational units the query names, one or more "
            f"of: {', '.join(organizational_units)}.\n"
        )
    else:
        units = "- organizational_unit: always null; no units can be inferred here.\n"
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
        f"{units}"
        "- date_from / date_to: inclusive ISO dates (YYYY-MM-DD), date_from on or "
        "before date_to.\n"
        "- parent_doc_id: always null.\n"
        "Only these business filters exist; you cannot select an organization or "
        "otherwise widen access."
    )


def has_any_filter(filters: RetrievalFilters) -> bool:
    """Whether `filters` narrows the search at all, or is the empty filter."""
    return filters != RetrievalFilters()


def describe_filters(filters: RetrievalFilters) -> str:
    """The filters as one line the calling model reads, e.g. `document_type=pdf or docx`."""
    parts = []
    for name, value in filters.model_dump(mode="json", exclude_none=True).items():
        shown = " or ".join(value) if isinstance(value, list) else str(value)
        parts.append(f"{name}={shown}")
    return "; ".join(parts)


def _grounded(filters: RetrievalFilters, organizational_units: Sequence[str]) -> RetrievalFilters:
    """The inferred filters with the two fields inference may not set freely removed.

    Only drops, so the result narrows no more than the validated object did and
    cannot become invalid - the empty list validation rejects is mapped to `None`.
    """
    allowed = set(organizational_units)
    inferred_units = filters.organizational_unit or []
    kept = [unit for unit in inferred_units if unit in allowed]
    if len(kept) < len(inferred_units):
        logger.info(
            "self_query_dropped_ungrounded_unit",
            extra={"dropped": len(inferred_units) - len(kept)},
        )
    return filters.model_copy(update={"organizational_unit": kept or None, "parent_doc_id": None})


async def infer_filters_from_query(
    model: AbstractModel,
    query: str,
    *,
    organizational_units: Sequence[str],
    today: date | None = None,
) -> RetrievalFilters | None:
    """Infer narrowing-only business filters from a natural-language query.

    Reuses the run's own model - the one whose credential the vault resolved - the
    way the LLM reminder and the compaction summary do, wrapped in `MeteredModel`
    so each response is booked against the run's ledger. That makes one inference
    one extra metered model request (two when its output needs correcting).

    Args:
        model: The run's model.
        query: The question the calling model searched with.
        organizational_units: The organizational units the searched collections
            carry, read under the same scope the search uses. The only values an
            inferred `organizational_unit` may keep.
        today: The date relative dates resolve against; today in UTC by default.

    Returns:
        A validated `RetrievalFilters` when the query clearly implies one; `None`
        when it implies none, when the model is not a request-response one, or when
        the nested run fails in one of the expected ways (`_INFERENCE_FAILURES`).
        `None` is the unfiltered fallback - a narrowing that did not happen, never a
        widening, since the tenant/collection scope is enforced by the caller
        regardless.

    Raises:
        BudgetExceeded: The run has reached a spend ceiling. Checked before the
            request, because the host agent's budget guard never sees it.
    """
    if not isinstance(model, Model):
        # A realtime model is not request-response, so it cannot run the inference.
        logger.info("self_query_skipped_not_a_request_model")
        return None

    await assert_ambient_budget()

    if len(organizational_units) > _MAX_GROUNDED_UNITS:
        logger.info(
            "self_query_units_not_grounded", extra={"unit_count": len(organizational_units)}
        )
        organizational_units = ()

    agent: Agent[None, RetrievalFilters] = Agent(
        MeteredModel(model),
        instructions=_instructions(today or datetime.now(UTC).date(), organizational_units),
        output_type=RetrievalFilters,
        retries=_OUTPUT_RETRIES,
    )
    try:
        result = await agent.run(query, usage_limits=_INFERENCE_LIMITS)
    except _INFERENCE_FAILURES:
        # An inferred value that fails the shared validation lands here too, after
        # the model's own retries - rejected exactly as a caller's would be, never
        # kept field by field as a partial filter.
        logger.warning("self_query_inference_failed", exc_info=True)
        return None

    filters = _grounded(result.output, organizational_units)
    return filters if has_any_filter(filters) else None


__all__ = ["describe_filters", "has_any_filter", "infer_filters_from_query"]
