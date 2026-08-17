"""Giving an agent the ability to draw an image, not just describe one."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.image_generation._toolset import build_image_toolset


@dataclass
class ImageGeneration(AbstractCapability[AgentDepsT]):
    """Lets an agent generate an image from a text prompt.

    The image is drawn by a dedicated image model this capability calls itself,
    so it works whatever the agent's own model is. Its spend is booked to the
    run's ledger, the result is stored organization-scoped, and - when the run
    has a workspace - the image is also written there for later steps to build
    with. See the package `README.md` for why the subagent is run here rather
    than reusing the library's, and why native image generation is not used.
    """

    model_id: str = "openai-responses:gpt-5.4"
    tool_settings: dict[str, Any] = field(default_factory=dict)
    # Unsealed from the vault by the factory. `repr=False` because a dataclass
    # repr ends up in log lines and traceback frames, and a provider key in
    # either is a key to rotate. `None` only on the preview and test paths that
    # build without a secret; a published agent always has one.
    api_key: str | None = field(default=None, repr=False)
    # The run's workspace backend when one is open, so a generated image can be
    # written into it. `None` for an agent without the sandbox capability, which
    # generates images all the same - it simply has nowhere to build with them.
    workspace_backend: Any | None = field(default=None, repr=False, compare=False)

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        if self._toolset is None:
            self._toolset = build_image_toolset(
                model_id=self.model_id,
                api_key=self.api_key,
                tool_settings=self.tool_settings,
                workspace_backend=self.workspace_backend,
            )
        return self._toolset
