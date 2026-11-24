"""Closed provider receipts for collecting an existing video without submitting again.

A receipt contains no key, URL or provider response. The workflow operation owns
its authorization, durable identity and credential generation; this value only
identifies the already-created job or file at its fixed catalog endpoint.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VideoReceipt(BaseModel):
    """An opaque, path-safe identifier bound to one provider API and model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["google", "byteplus", "xai", "alibaba"]
    api: Literal["gemini_interactions", "byteplus_tasks", "xai_videos", "dashscope_tasks"]
    model: str = Field(min_length=1, max_length=200)
    kind: Literal["job", "file"]
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,255}$")
