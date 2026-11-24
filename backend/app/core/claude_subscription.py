"""Nonsecret identity passed to the isolated, native Claude runtime."""

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

CLAUDE_SUBSCRIPTION_PROVIDER = "claude-subscription"
type ClaudeSubscriptionModel = Literal["sonnet", "opus", "haiku"]
CLAUDE_SUBSCRIPTION_MODELS: tuple[ClaudeSubscriptionModel, ...] = ("sonnet", "opus", "haiku")

type ClaudeSubscriptionThinking = bool | Literal["minimal", "low", "medium", "high", "xhigh", "max"]
CLAUDE_SUBSCRIPTION_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")

type ClaudeSubscriptionImageType = Literal["image/jpeg", "image/png", "image/gif", "image/webp"]
CLAUDE_SUBSCRIPTION_IMAGE_TYPES: tuple[ClaudeSubscriptionImageType, ...] = (
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
)


@dataclass(frozen=True)
class ClaudeSubscriptionImage:
    """In-memory image content for one inference; never a URL or a stored file."""

    media_type: ClaudeSubscriptionImageType
    data: bytes = field(repr=False)


@dataclass(frozen=True)
class ClaudeSubscriptionOwner:
    """An already-authorized personal connection, never an OAuth credential."""

    organization_id: UUID
    user_id: UUID

    def payload(self) -> dict[str, str]:
        return {"organization_id": str(self.organization_id), "user_id": str(self.user_id)}
