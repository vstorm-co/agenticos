"""What a person deciding a parked memory call reads on its card."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.agents.audience import RunAudience
from app.agents.deps import AgentDeps
from app.agents.memory_scope import readable_claim_scopes
from app.services import memory as memory_store

SHARE_PRIVATE_FIELDS = frozenset({"claim"})
"""The keys of a `share_memory` card that quote the run's memory."""


async def describe_share(deps: AgentDeps, args: Mapping[str, Any]) -> dict[str, str] | None:
    """The fact `share_memory` would share, and with whom.

    Read through every scope the run's audience may read, personal included
    whatever the binding says: the tool itself refuses a claim its binding cannot
    reach, so this only ever names more than the tool would act on, never less.
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
    claim = await memory_store.runtime.claim_for_approval(
        organization_id=deps.organization_id, claim_id=claim_id, scopes=scopes
    )
    if claim is None:
        return None
    return {"claim": claim.statement, "audience": str(args.get("to", ""))}
