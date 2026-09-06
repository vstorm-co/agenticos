"""Memory via mem0 - semantic recall kept outside this deployment."""

from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.memory_mem0._capability import MemoryMem0
from app.core.secret_kinds import ApiKeySecret, SecretKind, SecretRequirement

__all__ = [
    "MEMORY_MEM0_CAPABILITY_ID",
    "MemoryMem0",
    "MemoryMem0Config",
]

MEMORY_MEM0_CAPABILITY_ID = "memory_mem0"


class MemoryMem0Config(BaseModel):
    """Where the mem0 service is, and whether per-person memory is kept."""

    base_url: str | None = Field(
        default=None,
        max_length=500,
        description="Base URL of a self-hosted mem0; omit for mem0's managed cloud.",
    )
    allow_personal: bool = Field(
        default=True,
        description=(
            "Whether the agent keeps private memories for each person it talks to, "
            "readable only when it is alone with them. Off drops that store, for "
            "compliance or privacy; group-chat memory stays."
        ),
    )

    @field_validator("base_url")
    @classmethod
    def _base_url_is_a_valid_https_url(cls, value: str | None) -> str | None:
        """Settle the URL's shape at publish, not mid-run.

        An unparsable or non-https value would otherwise pass publication and
        reach `urlsplit` on the run path, outside its error handling, ending the
        run with a `ValueError`. The host allowlist stays a runtime check: it is a
        deployment setting a spec may outlive or be imported past, so it cannot be
        decided here.
        """
        if value is None:
            return None
        try:
            parsed = urlsplit(value)
        except ValueError as exc:
            raise ValueError("base_url is not a valid URL") from exc
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("base_url must be an https URL with a host")
        return value


@register(
    id=MEMORY_MEM0_CAPABILITY_ID,
    name="Memory (mem0)",
    category="knowledge",
    description=(
        "Let the agent remember facts and recall them by meaning, kept in a mem0 "
        "service - cloud or self-hosted - rather than in this deployment. A memory "
        "goes where the conversation goes, the same as a note does: one to one it "
        "is that person's, in a group chat it is the chat's. Nothing is stored "
        "here, so erasing a person's memory reaches mem0 through its own API."
    ),
    tools=(
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
    config_schema=MemoryMem0Config,
    secret=SecretRequirement(
        kind=SecretKind.API_KEY,
        description="The mem0 API key",
        # Without this the picker offers every `api_key` in the vault, because the
        # only other signal it has is `required_when` - and this key is needed
        # unconditionally, so there is no condition to read a service off (#1470).
        purpose="mem0",
    ),
)
def _build(ctx: CapabilityBuildContext) -> MemoryMem0 | None:
    """Build the capability from a binding's config and its sealed key.

    `None` without a key, rather than a capability whose every call refuses: the
    key is what makes this reachable at all, so an agent bound without one
    contributes no tools instead of two that always fail.
    """
    if not isinstance(ctx.secret, ApiKeySecret):
        return None
    config = ctx.config if isinstance(ctx.config, MemoryMem0Config) else MemoryMem0Config()
    return MemoryMem0(
        api_key=ctx.secret.api_key.get_secret_value(),
        base_url=config.base_url,
        allow_personal=config.allow_personal,
    )
