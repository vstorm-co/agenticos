"""Guardrails over a call's transcripts: detect, interrupt, log (#54, Q2)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from app.agents.capabilities.guardrails import (
    GuardrailBlocked,
    GuardrailsConfig,
    TranscriptScreens,
    transcript_screens,
)
from app.agents.spec import AgentSpec
from app.agents.voice import enabled_binding

logger = logging.getLogger(__name__)

WITHHELD = "[withheld by a guardrail]"


@dataclass(frozen=True)
class Screened:
    """A turn's text as it may be saved and shown, and whether a guardrail blocked it."""

    text: str
    blocked: bool


class TranscriptGuard:
    """One call's transcript screens, and how many times they blocked."""

    def __init__(self, screens: TranscriptScreens | None) -> None:
        self._screens = screens
        self.hits = 0

    @classmethod
    def for_spec(cls, spec: AgentSpec) -> TranscriptGuard:
        """The screens the agent's `guardrails` binding configures, or none without one."""
        binding = enabled_binding(spec, "guardrails")
        if binding is None:
            return cls(None)
        return cls(transcript_screens(GuardrailsConfig.model_validate(binding.config)))

    @property
    def screens_agent(self) -> bool:
        """Whether the agent's words are checked, so their captions wait for the check."""
        return self._screens is not None and self._screens.agent is not None

    def screen(self, text: str, *, speaker: Literal["user", "assistant"]) -> Screened:
        """The text to save and show. A block is withheld, counted and logged without its content."""
        if self._screens is None:
            return Screened(text=text, blocked=False)
        detector = self._screens.caller if speaker == "user" else self._screens.agent
        if detector is None:
            return Screened(text=text, blocked=False)
        try:
            verdict = detector(text)
        except GuardrailBlocked:
            self.hits += 1
            logger.info("voice_guardrail_hit", extra={"speaker": speaker})
            return Screened(text=WITHHELD, blocked=True)
        return Screened(
            text=str(verdict.replacement) if verdict.action == "replace" else text, blocked=False
        )
