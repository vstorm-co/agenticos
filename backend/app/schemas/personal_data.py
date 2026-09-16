"""What a person's own data looks like on the wire."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PersonalDataExport(BaseModel):
    """Everything this deployment holds about one person, as one document.

    A list per table rather than one flat stream, because a reader asking "what
    do you know about me" is asking a question per kind: which threads, which
    opinions, which devices, what an agent wrote down. Each list carries the
    fields named in `PersonalDataService` and no others - adding a column to a
    table must not silently add it to what every person can download.

    **The audit trail is deliberately absent.** An entry naming the person as an
    actor is the organization's record of what was done in it, not the person's
    data to take away - and an entry with its actor removed is worse than one
    naming a deleted account. `docs/security.md` says so in the same breath as
    the inventory.
    """

    exported_at: datetime = Field(description="When this document was produced.")
    profile: dict[str, Any] = Field(description="The account itself. Never the password hash.")
    conversations: list[dict[str, Any]] = Field(description="Threads this person started.")
    messages: list[dict[str, Any]] = Field(
        description=(
            "Every turn of those threads, answers included - a transcript with every "
            "second turn removed answers nothing."
        )
    )
    tool_calls: list[dict[str, Any]] = Field(
        description=(
            "What the agents did to answer those turns, with the arguments sent and "
            "what came back - a transcript without them says an agent did something "
            "and not what."
        )
    )
    memberships: list[dict[str, Any]] = Field(
        description="Which organizations they belong to, as what, and since when."
    )
    ratings: list[dict[str, Any]] = Field(description="Answers they marked good or bad.")
    sessions: list[dict[str, Any]] = Field(
        description="Where and when they signed in. Never the credential; the row holds a hash."
    )
    runs: list[dict[str, Any]] = Field(description="Runs they started, and what each cost.")
    memory: list[dict[str, Any]] = Field(
        description="What agents have written down about them, in every organization."
    )
    channel_identities: list[dict[str, Any]] = Field(
        description="The Slack, Telegram and Mattermost accounts they linked."
    )
    slash_commands: list[dict[str, Any]] = Field(description="Shortcuts they saved.")
    dashboard_layouts: list[dict[str, Any]] = Field(description="How they arranged their console.")


class PersonalDataPurge(BaseModel):
    """What a deletion removed that no cascade would have reached."""

    memory_notes: int = Field(description="Notes agents held about them, across organizations.")
    channel_identities: int = Field(
        description="Platform accounts removed rather than left unlinked."
    )
    workspaces: int = Field(
        description="User-scoped agent workspaces, which no cascade reaches either."
    )
