"""Giving an agent a voice: text in, an audio clip out."""

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.text_to_speech._toolset import OfferedVoice, build_speech_toolset


@dataclass
class TextToSpeech(AbstractCapability[AgentDepsT]):
    """Lets an agent speak a text aloud through the provider its author chose.

    The clip is made by the provider the binding names, so it works whatever the
    agent's own model is. Its cost is checked against the run's budget before the
    call and booked after it, the clip is stored organization-scoped, and - when
    the run has a workspace - written there too. See the package `README.md`.
    """

    provider: str
    model: str
    voice: str
    voices: tuple[OfferedVoice, ...] | None
    """What the agent may speak in, or `None` for any voice id in the account."""

    audio_format: str
    max_characters: int
    # Unsealed from the vault by the factory. `repr=False` because a dataclass
    # repr ends up in log lines and traceback frames, and a provider key in
    # either is a key to rotate. `None` only on the preview and test paths that
    # build without a secret; a published agent always has one.
    api_key: str | None = field(default=None, repr=False)
    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        if self._toolset is None:
            self._toolset = build_speech_toolset(
                provider=self.provider,
                model=self.model,
                voice=self.voice,
                voices=self.voices,
                audio_format=self.audio_format,
                max_characters=self.max_characters,
                api_key=self.api_key,
            )
        return self._toolset
