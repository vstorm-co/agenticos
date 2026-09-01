"""Memory capability - an agent's own store of named notes, kept across runs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import (
    CapabilityBinding,
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.memory._capability import Memory

__all__ = [
    "MEMORY_CAPABILITY_ID",
    "Memory",
    "MemoryConfig",
    "derive_end_user_scope_key",
    "per_user_partition_requested",
]

MEMORY_CAPABILITY_ID = "memory"


class MemoryConfig(BaseModel):
    """How an agent uses its memory."""

    enable_files: bool = Field(
        default=True,
        description="Named memory files the agent writes and reads back in later conversations.",
    )
    enable_facts: bool = Field(
        default=True,
        description="Short facts the agent remembers and recalls by meaning (semantic search).",
    )
    partition: Literal["shared", "per_user"] = Field(
        default="shared",
        description="Whether memory is one shared store or a private store per end-user.",
        json_schema_extra={
            "x-enum-labels": {
                "shared": "Shared — one memory per agent, for a single trusted audience",
                "per_user": "Per-user — a private memory for each end-user (needs an identified person)",
            }
        },
    )


def per_user_partition_requested(bindings: Iterable[CapabilityBinding]) -> bool:
    """Whether any enabled memory binding uses the `per_user` partition.

    Read off the raw binding config rather than a built capability, because the
    factory needs the answer *before* it derives the end-user key and builds
    anything. The default partition is `shared`, so an absent field is not
    `per_user` - which is what keeps the derivation (and the identity it reads)
    inert for every agent that does not ask for per-user memory.
    """
    return any(
        binding.enabled
        and binding.capability_id == MEMORY_CAPABILITY_ID
        and binding.config.get("partition") == "per_user"
        for binding in bindings
    )


def derive_end_user_scope_key(
    *,
    channel_identity_id: UUID | None,
    user_id: str | None,
    subject_is_publisher_fallback: bool,
) -> str | None:
    """The stable per-end-user key for a run, or `None` when there is no signal.

    A `per_user` store must attribute a memory to the *person asking*, and the
    trap is that on a hosted/widget surface `user_id` is the publisher, not the
    visitor (`publisher_context`), so keying on it alone would collapse every
    visitor onto the owner's partition - the cross-user leak this exists to stop.
    So:

    - a channel identity (linked or unlinked) is a stable per-account key;
    - otherwise a real subject (web chat, API, a linked member) keys on the user,
      but only when it is *not* the publisher fallback;
    - otherwise there is no per-person signal, and the caller refuses rather than
      writing into a shared owner partition.

    A consequence worth naming: a member linked to a channel keys on `chan:` in
    that channel and on `user:` on web or the API, so their per-user memory does
    not follow them across surfaces. Both keys are stable and neither leaks into
    anyone else's partition; a single cross-surface store is a v1 non-goal - it
    would need the channel-to-user link resolved here, which this pure function
    deliberately does not reach for.
    """
    if channel_identity_id is not None:
        return f"chan:{channel_identity_id}"
    if user_id is not None and not subject_is_publisher_fallback:
        return f"user:{user_id}"
    return None


@register(
    id=MEMORY_CAPABILITY_ID,
    name="Memory",
    category="knowledge",
    description=(
        "Give the agent a memory of its own - named notes and remembered facts it "
        "writes during a conversation and recalls in later ones."
    ),
    tools=(
        CapabilityToolInfo(
            id="list_memory",
            description="List the memories you have saved, by name and description.",
        ),
        CapabilityToolInfo(
            id="read_memory",
            description="Read one saved memory's body by its name.",
        ),
        CapabilityToolInfo(
            id="write_memory",
            description="Save a new memory under a name, so a later conversation can recall it.",
            side_effecting=True,
        ),
        CapabilityToolInfo(
            id="edit_memory",
            description="Replace the body of a memory you already saved.",
            side_effecting=True,
        ),
        CapabilityToolInfo(
            id="delete_memory",
            description="Forget a memory you saved, removing it entirely.",
            side_effecting=True,
        ),
        CapabilityToolInfo(
            id="remember",
            description="Remember a fact you will want to recall later by its meaning.",
            side_effecting=True,
        ),
        CapabilityToolInfo(
            id="recall",
            description="Recall facts relevant to a question, by meaning rather than exact words.",
        ),
    ),
    config_schema=MemoryConfig,
)
def _build(ctx: CapabilityBuildContext) -> Memory | None:
    """Build the memory capability from its validated config.

    Returns `None` when both stores are off, so an agent with memory disabled
    carries no memory tools and no dead switch - the "contributes nothing when
    its config says so" contract every capability keeps.
    """
    config = ctx.config if isinstance(ctx.config, MemoryConfig) else MemoryConfig()
    if not (config.enable_files or config.enable_facts):
        return None
    return Memory(
        partition=config.partition,
        enable_files=config.enable_files,
        enable_facts=config.enable_facts,
    )
