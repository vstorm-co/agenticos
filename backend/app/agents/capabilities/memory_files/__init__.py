"""Memory files - an agent's own notes, indexed by a `MEMORY.md` it maintains."""

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.memory_files._capability import MemoryFiles
from app.agents.capabilities.memory_files._toolset import INDEX_NAME

__all__ = [
    "INDEX_NAME",
    "MEMORY_FILES_CAPABILITY_ID",
    "MemoryFiles",
    "MemoryFilesConfig",
]

MEMORY_FILES_CAPABILITY_ID = "memory_files"


class MemoryFilesConfig(BaseModel):
    """How an agent keeps its notes.

    One field, and that is the point. This capability used to be one binding with
    six - two store toggles, two write levers, a backend and its URL - so a
    builder configured a matrix instead of picking a thing. Semantic recall (mem0) went with the organisation-wide store, which
    leaves exactly one genuine choice (#1470, #2090).
    """

    allow_personal: bool = Field(
        title="Keep private notes per person",
        default=True,
        description=(
            "Whether the agent keeps private notes for each person it talks to, "
            "readable only when it is alone with them. Off drops that store "
            "entirely, for compliance or privacy; the notes it keeps in group "
            "chats stay."
        ),
    )


@register(
    id=MEMORY_FILES_CAPABILITY_ID,
    name="Memory",
    category="knowledge",
    description=(
        "Let the agent keep its own notes across conversations, indexed by a "
        f"`{INDEX_NAME}` it maintains and is shown to it at the start of every "
        "request. A note goes where the conversation goes: one to one it is that "
        "person's and nobody else reads it, in a group chat it is the chat's and "
        "everyone in the chat reads it. Nothing an agent writes here is shared "
        "across people - standing knowledge you author belongs in context files."
    ),
    tools=(
        CapabilityToolInfo(
            id="list_memory",
            description="List your notes for this conversation, by name and description.",
        ),
        CapabilityToolInfo(
            id="read_memory",
            description="Read one note's body by its name.",
        ),
        CapabilityToolInfo(
            id="write_memory",
            description="Save a new note under a name, so a later conversation can find it.",
            side_effecting=True,
        ),
        CapabilityToolInfo(
            id="edit_memory",
            description="Replace the body of a note you already saved.",
            side_effecting=True,
        ),
        CapabilityToolInfo(
            id="delete_memory",
            description="Forget a note you saved, removing it entirely.",
            side_effecting=True,
        ),
        CapabilityToolInfo(
            id="remember",
            description="Record one durable fact, preference or decision, with where it came from.",
            side_effecting=True,
        ),
        CapabilityToolInfo(
            id="recall",
            description="Find recorded facts, preferences and decisions relevant to a question.",
        ),
        CapabilityToolInfo(
            id="correct_memory",
            description="Record the person's correction of a claim, keeping the history it corrects.",
            side_effecting=True,
        ),
        CapabilityToolInfo(
            id="share_memory",
            description="Share one claim with the project or the whole organization - only when asked.",
            side_effecting=True,
            always_requires_approval=True,
        ),
    ),
    config_schema=MemoryFilesConfig,
)
def _build(ctx: CapabilityBuildContext) -> MemoryFiles:
    """Build the capability from a binding's config.

    Never `None`: unlike the shape this replaces, there is no configuration that
    switches every store off, so a bound capability always contributes its tools.
    An agent that wants no notes does not bind it.
    """
    config = ctx.config if isinstance(ctx.config, MemoryFilesConfig) else MemoryFilesConfig()
    return MemoryFiles(allow_personal=config.allow_personal)
