"""A session's three-way merge of a fork with main, as the Changes step shows it."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.base import BaseSchema
from app.schemas.skill_version import VersionNumberRef

PartStateName = Literal["same", "fork", "main", "both", "conflict"]
Side = Literal["fork", "main"]


class MergeTextRead(BaseSchema):
    """One text of the merge - the description, or a part of the instructions.

    Parts are whole lines, line breaks included, and joining their results gives the
    instructions; nothing is trimmed.
    """

    model_config = ConfigDict(str_strip_whitespace=False)

    state: PartStateName = Field(
        description=(
            "Which side it comes from: `same` neither changed it, `fork` or `main` only that "
            "side did, `both` both made the same change, `conflict` they disagree"
        )
    )
    base: str = Field(description="The text where the fork was based")
    fork: str
    main: str
    result: str | None = Field(
        description="What the merge says; null for a conflict nobody has settled yet"
    )
    proposed: str | None = Field(
        default=None, description="The model's text for a conflict, kept beside a rewrite of it"
    )
    edited: bool = Field(description="A person wrote `result`")


class MergeFileSide(BaseSchema):
    description: str | None
    size_bytes: int


class MergeFileRead(BaseSchema):
    """One file of the merge; a side is null where the file is absent."""

    name: str
    state: PartStateName
    base: MergeFileSide | None
    fork: MergeFileSide | None
    main: MergeFileSide | None
    take: Side | None = Field(
        description="The side the merge keeps; null for a conflict waiting for a person"
    )


class SkillMergeRead(BaseSchema):
    """The merge a catch-up or a move to main works on."""

    id: UUID
    run_id: UUID
    skill_id: UUID
    fork_id: UUID
    kind: Literal["catch_up", "to_main"]
    base: VersionNumberRef = Field(description="The main version the fork is based on")
    fork: VersionNumberRef = Field(description="The fork's newest version")
    main: VersionNumberRef = Field(description="Main's newest version")
    description: MergeTextRead
    parts: list[MergeTextRead] = Field(description="The instructions, in order")
    files: list[MergeFileRead]
    conflicts: int = Field(description="Texts both sides changed differently")
    unresolved: int = Field(description="Texts and files still waiting; the check waits for none")
    updated_at: datetime | None = None


class MergeDescriptionEdit(BaseSchema):
    result: str = Field(min_length=1, max_length=500)


class MergePartEdit(BaseSchema):
    """A part's new text. Its last line ends as the part's sides end theirs."""

    model_config = ConfigDict(str_strip_whitespace=False)

    result: str


class MergeFilePick(BaseSchema):
    name: str
    take: Side
