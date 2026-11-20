"""Scoped short memories and durable notes."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.memory_files._approval import (
    CORRECTION_PRIVATE_FIELDS,
    SHARE_PRIVATE_FIELDS,
    correction_is_wide,
    describe_correction,
    describe_share,
)
from app.agents.capabilities.memory_files._capability import MemoryFiles
from app.agents.capabilities.memory_files._config import MemoryFilesConfig
from app.agents.capabilities.memory_files._toolset import INDEX_NAME

__all__ = [
    "INDEX_NAME",
    "MEMORY_FILES_CAPABILITY_ID",
    "MemoryFiles",
    "MemoryFilesConfig",
]

MEMORY_FILES_CAPABILITY_ID = "memory_files"


@register(
    id=MEMORY_FILES_CAPABILITY_ID,
    name="Memory",
    category="knowledge",
    description=(
        "Keep facts, preferences, decisions and longer notes across conversations. "
        "In private conversations, a short overview is available before the first tool call. "
        "A shared conversation can use its own permitted memories and notes."
    ),
    tools=(
        CapabilityToolInfo(
            id="list_memory",
            description="List your notes for this conversation, by name and description.",
            read_only=True,
        ),
        CapabilityToolInfo(
            id="read_memory",
            description="Read one note's body by its name.",
            read_only=True,
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
    describers={"share_memory": describe_share, "correct_memory": describe_correction},
    private_approval_fields={
        "share_memory": SHARE_PRIVATE_FIELDS,
        "correct_memory": CORRECTION_PRIVATE_FIELDS,
    },
    always_asks_when={"correct_memory": correction_is_wide},
)
def _build(ctx: CapabilityBuildContext) -> MemoryFiles:
    """Build the capability from a binding's config.

    Never `None`: unlike the shape this replaces, there is no configuration that
    switches every store off, so a bound capability always contributes its tools.
    An agent that wants no notes does not bind it.
    """
    config = ctx.config if isinstance(ctx.config, MemoryFilesConfig) else MemoryFilesConfig()
    return MemoryFiles(allow_personal=config.allow_personal, inject_context=config.inject_context)
