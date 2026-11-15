"""How a bound memory capability is configured."""

from pydantic import BaseModel, Field


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
