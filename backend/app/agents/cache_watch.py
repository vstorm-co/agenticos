"""Prompt-cache busts, reported per run, agent and model (#2109).

Caching pays only while the start of each request - tools, instructions,
history - stays byte-identical. When something moves it, the provider charges
the full input rate for tokens it could have served from cache, and nobody
notices except on the invoice.

Every agent carries :class:`CacheWatch`. It reads the provider's own cache figures
on each response through Pydantic AI's cache-health detector - the one behind the
`pydantic_ai.cache.*` span attributes and `pydantic_ai-harness`'s
`WarnOnCacheBusts` - and tells a *bust* (the cached prefix collapsed while the
provider should still have held it: the prefix moved) from an *expiry* (the
retention window passed). Rather than `warnings.warn`, which is process-global
and says nothing about whose run it was, each one is written onto the request it
happened at in the run's manifest - the run view's request waterfall - and logged
with the agent and model, for whoever is investigating cost. A delegate's own
requests are not rows of its parent's waterfall, so its events are in the log.

The detector's marks are kept per conversation in one store for the process, so
the first request of a turn is judged against what the previous turn cached:
that is where a moved prefix most often hides. A turn served by another worker
starts from no mark and is not compared.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic_ai._cache_health import (
    CacheHealthDetector,
    CollapseReason,
    ConversationCacheMarkStore,
)
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelResponse
from pydantic_ai.tools import RunContext

from app.agents.deps import AgentDeps
from app.agents.manifest import RunRecorder

if TYPE_CHECKING:
    from pydantic_ai.models import ModelRequestContext

logger = logging.getLogger(__name__)

CacheEvent = Literal["bust", "expired"]

_MARKS = ConversationCacheMarkStore()
"""Every conversation's established cache prefix, per provider and model, in this process."""

_EVENT: dict[CollapseReason, CacheEvent] = {
    "unexpected": "bust",
    "unknown": "bust",
    "ttl_expired": "expired",
}
"""How each collapse the detector classifies is reported. `unknown` is a provider that
publishes no retention window, so a bust cannot be told from an expiry and is
reported as the one worth looking at; `compacted` and `unreported` are not reported."""


@dataclass
class CacheWatch(AbstractCapability[AgentDeps]):
    """Notes each prompt-cache bust or expiry on the request it happened at."""

    recorder: RunRecorder
    marks_key: str | None = None
    """Whose marks these are: a conversation and the agent in it, or `None` for a
    run with no conversation, which is judged alone. The agent is part of it
    because a delegate in the same thread has its own instructions and tools, and
    so its own prefix - judged against its parent's, every turn would be a bust."""
    agent_id: UUID | None = None
    _detector: CacheHealthDetector | None = field(default=None, init=False, repr=False)

    async def after_model_request(
        self,
        ctx: RunContext[AgentDeps],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        if self._detector is None:
            self._detector = CacheHealthDetector(
                _MARKS,
                self.marks_key,
                ctx.run_id,
                alert_on=frozenset(_EVENT),
            )
        health = self._detector.observe(request_context, response)
        collapse = None if health is None else health.collapse
        if collapse is None or not collapse.alert or collapse.reason not in _EVENT:
            return response
        event = _EVENT[collapse.reason]
        # The recording model took this response down as it arrived, before any
        # capability saw it, so it is the last request recorded.
        self.recorder.requests[-1].cache = event
        self.recorder.requests[-1].cache_missed_tokens = collapse.missed_tokens
        logger.warning(
            "prompt_cache_%s",
            event,
            extra={
                "agent_id": str(self.agent_id) if self.agent_id else None,
                "model": response.model_name,
                "provider": response.provider_name,
                "reason": collapse.reason,
                "missed_tokens": collapse.missed_tokens,
                "established_tokens": collapse.previous.established_tokens,
            },
        )
        return response


@dataclass(frozen=True)
class CacheTally:
    """What one run's requests - its delegates' included - lost to the prompt cache."""

    busts: int
    expiries: int
    missed_tokens: int


def tally(*recorders: RunRecorder) -> CacheTally:
    """Count the busts and expiries `CacheWatch` marked on a run's requests - its
    own agent's and every delegate's."""
    marked = [
        request
        for recorder in recorders
        for request in recorder.requests
        if request.cache is not None
    ]
    return CacheTally(
        busts=sum(request.cache == "bust" for request in marked),
        expiries=sum(request.cache == "expired" for request in marked),
        missed_tokens=sum(request.cache_missed_tokens for request in marked),
    )
