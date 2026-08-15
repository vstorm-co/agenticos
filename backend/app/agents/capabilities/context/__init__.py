"""Context capability - an organization's standing context, injected or linked."""

from pydantic import BaseModel, Field

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


class ContextConfig(BaseModel):
    """How the agent uses its bound context files."""

    expose_read_tool: bool = Field(
        default=True,
        description=(
            "Whether link-mode files are reachable through a read tool. Off means "
            "only injected files reach the model, and nothing is read on demand."
        ),
    )


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
            mode=file.mode,
            format=file.format,
        )
        for file in files
    )
    capability = Context(items=items, expose_read_tool=config.expose_read_tool)
    if capability.get_instructions() is None and capability.get_toolset() is None:
        return None
    return capability
