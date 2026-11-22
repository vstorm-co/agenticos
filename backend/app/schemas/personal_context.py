"""Source-attributed input and proposals shared by background work and offline replay."""

from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator


class ContextTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    thread_id: str
    occurred_at: AwareDatetime
    speaker_id: str
    role: Literal["user", "assistant"]
    text: str


class ContextPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: AwareDatetime
    subject_id: str
    audience: Literal["private", "shared"]
    profile: dict[str, JsonValue]
    messages: list[ContextTurn]
    memory: list[dict[str, JsonValue]]
    tool_receipts: list[dict[str, JsonValue]]
    current_state: dict[str, JsonValue]
    available_features: list[dict[str, JsonValue]]
    changed_source_ids: list[str]


class SourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_id: str = Field(
        min_length=1,
        max_length=180,
        description="Exact supplied key: message:<id>, receipt:<id>, task:<id>, memory:<id> or feature:<id>; never a bare UUID",
    )
    quote: str = Field(min_length=4, max_length=500)


class WorkTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    summary: str = Field(min_length=1, max_length=900)
    state: Literal["open", "completed", "unknown", "not_work"]
    subject_owned: bool
    intent: Literal["one_off", "repeatable", "explicit_automation", "context"] = "one_off"
    evidence: list[SourceEvidence] = Field(min_length=1, max_length=8)


class ContextDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topics: list[WorkTopic] = Field(default_factory=list, max_length=8)


class PersonalAdvice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    kind: Literal["agent", "routine", "task", "attention", "feature_tip"]
    title: str = Field(min_length=1, max_length=120)
    detail: str = Field(min_length=1, max_length=400)
    chat_prompt: str = Field(min_length=1, max_length=2400)
    evidence: list[SourceEvidence] = Field(min_length=1, max_length=8)
    resource_ids: list[str] = Field(default_factory=list, max_length=8)
    feature_id: str | None = Field(default=None, max_length=80)
    # Local intent is kept as text, never fabricated as a UTC cron. Approval-time
    # configuration owns timezone-aware scheduling and genuinely missing choices.
    proposed_schedule: str | None = Field(default=None, max_length=200)


class PersonalReading(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opportunities: list[PersonalAdvice] = Field(default_factory=list, max_length=4)
    starters: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def distinct_identities(self) -> Self:
        identities = [card.identity for card in self.opportunities]
        if len(identities) != len(set(identities)):
            raise ValueError("Propose each underlying job only once")
        return self


class VerifiedReading(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved_identities: list[str] = Field(default_factory=list, max_length=4)
    corrections: list[PersonalAdvice] = Field(default_factory=list, max_length=4)


class ConversationContext(BaseModel):
    revision: str
    digests: list[ContextDigest]
    messages: list[ContextTurn]
    receipts: list[dict[str, JsonValue]]
