"""Memory capability - an agent's own store of named notes, kept across runs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.agents.capabilities._registry import (
    CapabilityBinding,
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.memory._capability import Memory
from app.agents.memory_scope import MemoryAudience, derive_audience
from app.core.secret_kinds import ApiKeySecret, SecretCondition, SecretKind, SecretRequirement

__all__ = [
    "MEMORY_CAPABILITY_ID",
    "Memory",
    "MemoryConfig",
    "memory_audience_for",
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
            "Whether the agent keeps a private memory for each person it talks to, "
            "readable only when it is alone with them. Off drops that store entirely, "
            "for compliance or privacy; group-chat and organisation memory stay."
        ),
    )
    allow_agent_shared_writes: bool = Field(
        default=True,
        description=(
            "Whether the agent may write to the organisation-wide memory — the one "
            "direction that reaches more people than the conversation it came from. "
            "Off keeps that store curated by operators; the agent still reads it, and "
            "still saves to the memory of the conversation it is in."
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

    @field_validator("mem0_base_url")
    @classmethod
    def _mem0_base_url_is_a_valid_https_url(cls, value: str | None) -> str | None:
        """Settle the URL's shape at publish, not mid-run.

        An unparsable or non-https value would otherwise pass publication and
        reach `urlsplit` on the run path, outside its HTTP error handling,
        ending the run with a `ValueError`. The host allowlist stays a runtime
        check: it is a deployment setting a spec may outlive or be imported
        past, so it cannot be decided here.
        """
        if value is None:
            return None
        try:
            parsed = urlsplit(value)
        except ValueError as exc:
            raise ValueError("mem0_base_url is not a valid URL") from exc
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("mem0_base_url must be an https URL with a host")
        return value

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

    The factory derives the run's memory audience whenever memory is bound, because
    every memory agent reads at least the organization's store. Read off the raw
    binding config rather than a built capability, because the factory needs the
    answer before it derives the audience and builds anything; the audience stays
    `None` for every agent without memory.
    """
    return any(
        binding.enabled and binding.capability_id == MEMORY_CAPABILITY_ID for binding in bindings
    )


def memory_audience_for(
    *,
    channel_identity_id: UUID | None,
    user_id: str | None,
    subject_is_publisher_fallback: bool,
    room_key: str | None,
) -> MemoryAudience:
    """The run's memory audience, from the identity the request arrived with.

    A thin re-export of :func:`app.agents.memory_scope.derive_audience` so the
    factory reaches the capability's vocabulary through the capability package,
    the way it does for every other capability. The reasoning is in that module.
    """
    return derive_audience(
        channel_identity_id=channel_identity_id,
        user_id=user_id,
        subject_is_publisher_fallback=subject_is_publisher_fallback,
        room_key=room_key,
    )


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
        # The config validator forces backend to native when facts are off, so the
        # key is asked for exactly when it will be used.
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
