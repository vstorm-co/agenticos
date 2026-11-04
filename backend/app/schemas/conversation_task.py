"""The member-facing state of a delegated topic; execution context stays private."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_conversation_id: UUID
    conversation_id: UUID
    agent_id: UUID
    title: str
    status: Literal[
        "queued",
        "running",
        "awaiting_approval",
        "awaiting_answer",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
    ]
    delivery: Literal["pending", "running", "delivered", "interrupted", "withdrawn"]
    run_id: UUID | None
    return_run_id: UUID | None
    outcome: str | None
    created_at: datetime


class StartConversationTask(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=16000)
    agent_id: UUID | None = None
