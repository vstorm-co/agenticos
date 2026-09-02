"""Memory capability - an agent's own store of named notes, kept across runs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.agents.capabilities._registry import (
    CapabilityBinding,
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.memory._capability import Memory
from app.core.secret_kinds import ApiKeySecret, SecretCondition, SecretKind, SecretRequirement

__all__ = [
    "MEMORY_CAPABILITY_ID",
    "Memory",
    "MemoryConfig",
    "derive_end_user_scope_key",
    "memory_requested",
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
    allow_personal: bool = Field(
        default=True,
        description=(
            "Whether the agent keeps a private memory for each identified end-user, "
            "alongside the shared store. Off makes memory shared-only, for compliance "
            "or privacy."
        ),
    )
    allow_agent_shared_writes: bool = Field(
        default=True,
        description=(
            "Whether the agent may write to the shared, organisation-wide memory. Off "
            "keeps the shared store curated by operators — the agent still reads it, "
            "but saves only to its personal memory."
        ),
    )
    backend: Literal["native", "mem0"] = Field(
        default="native",
        description="Where facts are stored: this deployment's pgvector, or a mem0 service.",
        json_schema_extra={
            "x-enum-labels": {
                "native": "Native — facts in this deployment's own pgvector store",
                "mem0": "mem0 — facts in a mem0 service (cloud or self-hosted); needs an API key",
            }
        },
    )
    mem0_base_url: str | None = Field(
        default=None,
        max_length=500,
        description="Base URL of a self-hosted mem0; omit for mem0's managed cloud.",
    )

    @model_validator(mode="after")
    def _mem0_requires_facts(self) -> MemoryConfig:
        """mem0 stores facts and nothing else, so it is meaningless without them.

        Normalising `backend` to `native` when facts are off is what lets the
        conditional `SecretRequirement` key on `backend == "mem0"` alone: without
        this, a files-only agent that happened to pick `mem0` would be asked for
        an API key it can never use (H1, the `browser_use` pattern)."""
        if not self.enable_facts:
            self.backend = "native"
        return self


def memory_requested(bindings: Iterable[CapabilityBinding]) -> bool:
    """Whether any enabled memory binding is present.

    The factory derives the per-end-user partition key whenever memory is bound,
    because every memory agent now reads its shared store and, when the run has an
    identified person, that person's personal store too. Read off the raw binding
    config rather than a built capability, because the factory needs the answer
    before it derives the key and builds anything; the key stays `None`, and
    personal memory inert, for every agent without memory and for a run with no
    per-person signal.
    """
    return any(
        binding.enabled and binding.capability_id == MEMORY_CAPABILITY_ID for binding in bindings
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
    secret=SecretRequirement(
        kind=SecretKind.API_KEY,
        description="The mem0 API key, when facts are stored in a mem0 service",
        # Only the mem0 backend authenticates; native pgvector needs no key. The
        # config validator forces backend to native when facts are off, so this
        # is asked for exactly when it will be used (H1).
        required_when=SecretCondition(field="backend", equals=("mem0",)),
    ),
)
def _build(ctx: CapabilityBuildContext) -> Memory | None:
    """Build the memory capability from its validated config.

    Returns `None` when both stores are off, so an agent with memory disabled
    carries no memory tools and no dead switch - the "contributes nothing when
    its config says so" contract every capability keeps. When facts are backed by
    mem0, the unsealed key is read from `ctx.secret` and handed to the capability;
    the model never sees it, and files stay native regardless of the backend.
    """
    config = ctx.config if isinstance(ctx.config, MemoryConfig) else MemoryConfig()
    if not (config.enable_files or config.enable_facts):
        return None
    mem0_api_key = (
        ctx.secret.api_key.get_secret_value() if isinstance(ctx.secret, ApiKeySecret) else None
    )
    return Memory(
        enable_files=config.enable_files,
        enable_facts=config.enable_facts,
        allow_personal=config.allow_personal,
        allow_agent_shared_writes=config.allow_agent_shared_writes,
        backend=config.backend,
        mem0_base_url=config.mem0_base_url,
        mem0_api_key=mem0_api_key,
    )
