"""Schemas for automatic skill learning (feature #9).

The request identifies a proposal from the failure-learning loop (#32). The
service resolves that row within the organization and agent, and verifies the
submitted text and provenance against the applied proposal before learning.
The service never mines failures or proposes changes.
"""

from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class LearnSkillCreate(BaseSchema):
    """Learn one approved skill-target proposal into the skill catalog.

    The proposal row supplies the target and audit provenance. Optional
    caller-supplied provenance must match that row; omitted values are read
    from it. `pattern_key` is resolved from the linked ledger entry. `name`
    and `description` remain accepted for compatibility and do not affect
    learning. `base_content_sha256` guards against overwriting a skill that
    changed after the proposal was written.
    """

    proposal_id: UUID = Field(description="The #32 proposal this learning comes from")
    skill_id: UUID | None = Field(
        default=None,
        description="Optional expected target skill; must match the stored proposal when supplied",
    )
    name: str | None = Field(
        default=None,
        max_length=64,
        deprecated=True,
        description="Deprecated: accepted and ignored. Learning never renames the target skill.",
    )
    description: str | None = Field(
        default=None,
        max_length=500,
        deprecated=True,
        description="Deprecated: accepted and ignored. Learning never changes the target skill's description.",
    )
    content: str = Field(
        min_length=1,
        description="The learned text — the proposal's `new_text`, in full",
    )
    rationale: str | None = Field(
        default=None, description="Why the proposal was written, for the audit trail"
    )
    ledger_entry_id: UUID | None = Field(
        default=None, description="The #32 ledger entry whose pattern motivated the proposal"
    )
    pattern_key: str | None = Field(
        default=None,
        max_length=120,
        description="Legacy input; audit provenance uses the linked ledger entry",
    )
    base_content_sha256: str | None = Field(
        default=None,
        max_length=64,
        description="SHA-256 of the skill content the proposal was written against",
    )


class LearnedSkillRead(BaseSchema):
    """The skill as learned, and where it came from."""

    skill_id: UUID
    name: str
    version: int = Field(description="The catalog version after learning — see `Skill.version`")
    content_sha256: str = Field(description="SHA-256 of the learned content, as stored")
    created: bool = Field(
        ...,
        deprecated=True,
        description="Deprecated: always false. Learning updates an existing skill and never creates one.",
    )
    already_learned: bool = Field(
        description=(
            "True when the skill already carried exactly this text: the call "
            "wrote nothing, so learning the same approved proposal twice is safe"
        )
    )
    proposal_id: UUID
    ledger_entry_id: UUID | None = None
    pattern_key: str | None = None
