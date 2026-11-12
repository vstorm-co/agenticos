"""What a person deciding a parked memory call reads on its card."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.agents.audience import RunAudience
from app.agents.capabilities.memory_files._config import MemoryFilesConfig
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


async def _named_claim(
    deps: AgentDeps, args: Mapping[str, Any], *, allow_personal: bool, only_wide: bool = False
) -> ClaimView | None:
    """The live claim a call names, if the run's audience may read it, else `None`."""
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
        allow_personal=allow_personal,
    )
    if only_wide:
        scopes = [
            scope
            for scope in scopes
            if scope.scope_key.startswith((ORGANIZATION_PREFIX, PROJECT_PREFIX))
        ]
    return await memory_store.runtime.claim_for_approval(
        organization_id=deps.organization_id, claim_id=claim_id, scopes=scopes
    )


def _personal(config: BaseModel | None) -> bool:
    """Whether the binding keeps personal notes, as the tools read it."""
    settings = config if isinstance(config, MemoryFilesConfig) else MemoryFilesConfig()
    return settings.allow_personal


async def describe_share(
    deps: AgentDeps, args: Mapping[str, Any], config: BaseModel | None
) -> dict[str, str] | None:
    """The fact `share_memory` would share, and with whom.

    Read through the same scopes the tool reads, so the card never names a claim
    the tool would refuse - a personal one where the binding keeps no personal
    notes, say.
    """
    claim = await _named_claim(deps, args, allow_personal=_personal(config))
    if claim is None:
        return None
    return {"claim": claim.statement, "audience": str(args.get("to", ""))}


async def describe_correction(
    deps: AgentDeps, args: Mapping[str, Any], config: BaseModel | None
) -> dict[str, str] | None:
    """The fact `correct_memory` would replace, and what it would say instead.

    Read through the same scopes the tool reads, as for `describe_share`.
    """
    claim = await _named_claim(deps, args, allow_personal=_personal(config))
    if claim is None:
        return None
    return {"before": claim.statement, "after": str(args.get("statement", ""))}


async def correction_is_wide(deps: AgentDeps, args: Mapping[str, Any]) -> bool:
    """Whether `correct_memory` would change a fact a whole project or organization reads.

    Reads no personal scope: a fact in one is never wide, so there is nothing to learn there.
    """
    # Disabling personal memory drops wide scopes too for a private audience.
    # Resolve normal access first, then query only the project/organization stores.
    claim = await _named_claim(deps, args, allow_personal=True, only_wide=True)
    return claim is not None and claim.scope in _WIDE_SCOPES
