"""Context capability - an organization's standing context, injected or linked."""

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.context._capability import Context, ContextItem

__all__ = [
    "CONTEXT_BODIES_RESOURCE",
    "CONTEXT_FILES_RESOURCE",
    "Context",
    "ContextBody",
    "ContextConfig",
]

# The key the runner files the resolved context files under, read back by the
# builder below. A named constant rather than a bare string on both sides,
# because a typo in one of two copies is a capability that silently sees nothing.
CONTEXT_FILES_RESOURCE = "context_files"

CONTEXT_BODIES_RESOURCE = "context_bodies"
"""Bodies that stand in for stored context files on this run, keyed by file id.

Set only by an eval that checks a proposed context change: the candidate reads
the proposed body where the stored one would be, and nothing is written to the file.
"""


@dataclass(frozen=True)
class ContextBody:
    """A context file's description and body, as a proposal would leave them."""

    description: str | None
    content: str


class ContextConfig(BaseModel):
    """How the agent uses its bound context files."""

    expose_read_tool: bool = Field(
        title="Let the agent open linked files",
        default=True,
        description=(
            "Whether link-mode files are reachable through a read tool. Off means "
            "only injected files reach the model, and nothing is read on demand."
        ),
    )


@register(
    id="context",
    read_only=True,
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
    bodies = ctx.resources.get(CONTEXT_BODIES_RESOURCE) or {}
    config = ctx.config if isinstance(ctx.config, ContextConfig) else ContextConfig()
    items = tuple(
        ContextItem(
            name=file.name,
            description=file.description if body is None else body.description,
            content=file.content if body is None else body.content,
            mode=file.mode,
            format=file.format,
        )
        for file in files
        for body in (bodies.get(file.id) if bodies else None,)
    )
    capability = Context(items=items, expose_read_tool=config.expose_read_tool)
    if capability.get_instructions() is None and capability.get_toolset() is None:
        return None
    return capability
