"""What a person deciding a parked memory call reads on its card."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.agents.audience import RunAudience
from app.agents.deps import AgentDeps
from app.agents.memory_scope import readable_claim_scopes
from app.core.memory_keys import ORGANIZATION_PREFIX, PROJECT_PREFIX
from app.services import memory as memory_store
from app.services.memory._runtime import ClaimView

SHARE_PRIVATE_FIELDS = frozenset({"claim"})
"""The keys of a `share_memory` card that quote the run's memory."""

CORRECTION_PRIVATE_FIELDS = frozenset({"before", "after", "statement"})
"""The keys of a `correct_memory` call and card that quote the run's memory."""

_WIDE_SCOPES = frozenset(
    prefix.removesuffix(":") for prefix in (ORGANIZATION_PREFIX, PROJECT_PREFIX)
)


async def _named_claim(deps: AgentDeps, args: Mapping[str, Any]) -> ClaimView | None:
    """The live claim a call names, read through every scope the run's audience may read.

    Personal scopes are included whatever the binding says: the tools refuse a
    claim their binding cannot reach, so this only ever names more than a tool
    would act on, never less.
    """
    if deps.organization_id is None or deps.agent_id is None:
        return None
    try:
        claim_id = UUID(str(args.get("claim_id", "")))
    except ValueError:
        return None
    scopes = readable_claim_scopes(
        deps.audience or RunAudience(),
        organization_id=deps.organization_id,
        agent_id=deps.agent_id,
        project_id=await memory_store.runtime.project_of(deps.conversation_id),
        allow_personal=True,
    )
    return await memory_store.runtime.claim_for_approval(
        organization_id=deps.organization_id, claim_id=claim_id, scopes=scopes
    )


async def describe_share(deps: AgentDeps, args: Mapping[str, Any]) -> dict[str, str] | None:
    """The fact `share_memory` would share, and with whom."""
    claim = await _named_claim(deps, args)
    if claim is None:
        return None
    return {"claim": claim.statement, "audience": str(args.get("to", ""))}


async def describe_correction(deps: AgentDeps, args: Mapping[str, Any]) -> dict[str, str] | None:
    """The fact `correct_memory` would replace, and what it would say instead."""
    claim = await _named_claim(deps, args)
    if claim is None:
        return None
    return {"before": claim.statement, "after": str(args.get("statement", ""))}


async def correction_is_wide(deps: AgentDeps, args: Mapping[str, Any]) -> bool:
    """Whether `correct_memory` would change a fact a whole project or organization reads."""
    claim = await _named_claim(deps, args)
    return claim is not None and claim.scope in _WIDE_SCOPES
