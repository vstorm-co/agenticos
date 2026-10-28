"""Context capability - an organization's standing context, injected or linked."""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.agents.spec import CapabilityBindingSpec

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.context._capability import Context, ContextItem

__all__ = ["CONTEXT_FILES_RESOURCE", "Context", "ContextConfig"]

# The key the runner files the resolved context files under, read back by the
# builder below. A named constant rather than a bare string on both sides,
# because a typo in one of two copies is a capability that silently sees nothing.
CONTEXT_FILES_RESOURCE = "context_files"


class ContextFileSettings(BaseModel):
    """How one agent uses a shared file; independent of every other agent."""

    mode: Literal["inject", "link"] = Field(
        default="inject",
        title="How to use it",
        description="Include in every answer, or read on demand.",
    )
    enabled: bool = Field(
        default=True,
        title="Use this file",
        description="Whether this agent may use the attached file.",
    )


class ContextConfig(BaseModel):
    """How the agent uses its bound context files."""

    file_settings: dict[UUID, ContextFileSettings] = Field(
        default_factory=dict,
        title="How each file is used",
        description="Per-agent mode and availability for attached context files. An absent entry preserves the file's legacy defaults.",
    )

    expose_read_tool: bool = Field(
        title="Let the agent open linked files",
        default=True,
        description=(
            "Whether link-mode files are reachable through a read tool. Off means "
            "only injected files reach the model, and nothing is read on demand."
        ),
    )


def context_config(bindings: Sequence[CapabilityBindingSpec]) -> ContextConfig:
    """The context policy on this agent, with old empty configurations preserved."""
    binding = next((item for item in bindings if item.id == "context"), None)
    return ContextConfig.model_validate(binding.config) if binding is not None else ContextConfig()


@register(
    id="context",
    name="Context",
    category="knowledge",
    description=(
        "Put the organization's standing context into the agent - a glossary, a "
        "policy, a brand voice - injected into the prompt or read on demand."
    ),
    tools=(
        CapabilityToolInfo(
            id="list_context",
            description="List the reference files available to read, by name and description.",
        ),
        CapabilityToolInfo(
            id="read_context",
            description="Read one reference file's body by its name.",
        ),
    ),
    config_schema=ContextConfig,
)
def _build(ctx: CapabilityBuildContext) -> Context | None:
    """Build the capability from the files the runner resolved.

    Returns `None` when nothing usable is bound - no files at all, or only linked
    files with the read tool turned off - so a run carries no empty preamble and
    no tool that can only report that there is nothing to read.
    """
    files = ctx.resources.get(CONTEXT_FILES_RESOURCE) or []
    config = ctx.config if isinstance(ctx.config, ContextConfig) else ContextConfig()
    items = tuple(
        ContextItem(
            name=file.name,
            description=file.description,
            content=file.content,
            mode=config.file_settings[file.id].mode
            if file.id in config.file_settings
            else file.mode,
            format=file.format,
        )
        for file in files
        if file.id not in config.file_settings or config.file_settings[file.id].enabled
    )
    capability = Context(items=items, expose_read_tool=config.expose_read_tool)
    if capability.get_instructions() is None and capability.get_toolset() is None:
        return None
    return capability
