"""Claude Code or Codex, working in the agent's sandbox at the model's request."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.coding_agent._harness import LABELS, Access, Harness
from app.agents.capabilities.coding_agent._toolset import SignIn, build_coding_toolset


@dataclass
class CodingAgent(AbstractCapability[AgentDepsT]):
    """Hands software work to a coding harness running in the run's sandbox.

    See the package `README.md` for why the harness is driven headless through
    the sandbox's shell rather than over ACP, and why its approval is one
    decision per task.
    """

    harness: Harness = "claude_code"
    access: Access = "edit"
    model: str | None = None
    base_url: str | None = None
    timeout_seconds: int = 900
    # Unsealed from the vault by the factory; `repr=False` for the reason
    # `ImageGeneration.api_key` gives - a repr reaches log lines and tracebacks.
    api_key: str | None = field(default=None, repr=False)
    # A ChatGPT sign-in, as where its tokens live for an organization - ids, not
    # tokens - rather than as the tokens themselves; see `_build`.
    sign_in: SignIn | None = None
    # Whether other people's runs work in the same container - a project's, an
    # agent's, a channel's - where a sign-in's tokens could be read by them.
    shared_sandbox: bool = False
    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_instructions(self) -> str:
        label = LABELS[self.harness]
        reach = (
            "reads the code, edits files and runs commands such as tests"
            if self.access == "edit"
            else "reads and searches the code and answers, changing nothing"
        )
        return (
            f"You can hand software work to {label}, a coding agent that works in your "
            f"sandbox: it {reach}. Use run_coding_agent with the whole task, then tell "
            "the person what it found or did. Its later tasks in this conversation "
            "continue the same session."
        )

    def get_toolset(self) -> AbstractToolset[Any]:
        if self._toolset is None:
            self._toolset = build_coding_toolset(
                harness=self.harness,
                access=self.access,
                model=self.model,
                base_url=self.base_url,
                api_key=self.api_key,
                sign_in=self.sign_in,
                shared_sandbox=self.shared_sandbox,
                timeout_seconds=self.timeout_seconds,
            )
        return self._toolset
