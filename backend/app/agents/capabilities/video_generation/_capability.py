"""Giving an agent a camera: a description in, a short video out."""

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.video_generation._toolset import VideoSettings, build_video_toolset


@dataclass
class VideoGeneration(AbstractCapability[AgentDepsT]):
    """Lets an agent make a short video through the provider its author chose.

    The clip is made by the provider the binding names, whatever the agent's own
    model is. Its cost is checked against the run's budget before the job is
    submitted and booked after it, the clip is stored organization-scoped, and -
    when the run has a workspace - written there too. See the package `README.md`.
    """

    provider: str
    model: str
    resolution: str
    aspect_ratio: str
    seconds: int
    max_seconds: int
    audio: bool | None
    timeout_seconds: int
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
            self._toolset = build_video_toolset(
                VideoSettings(
                    provider=self.provider,
                    model=self.model,
                    resolution=self.resolution,
                    aspect_ratio=self.aspect_ratio,
                    seconds=self.seconds,
                    max_seconds=self.max_seconds,
                    audio=self.audio,
                    timeout_seconds=self.timeout_seconds,
                ),
                api_key=self.api_key,
            )
        return self._toolset
