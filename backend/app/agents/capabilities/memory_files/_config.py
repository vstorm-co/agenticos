"""How a bound memory capability is configured."""

from pydantic import BaseModel, Field


class MemoryFilesConfig(BaseModel):
    """Privacy and automatic prompt context for a bound Memory capability."""

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

    inject_context: bool = Field(
        title="Include memory automatically",
        default=True,
        description=(
            "Show a bounded summary of personal memories and notes in private conversations. "
            "Off keeps memory tools and background maintenance available."
        ),
    )
