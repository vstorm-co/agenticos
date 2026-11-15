"""One of the coding CLIs, kept as a session the agent drives across turns."""

from dataclasses import dataclass, field
from typing import Any

from pydantic import SecretStr
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.coding_agent._harness import LABELS, Access, Harness
from app.agents.capabilities.harness._toolset import build_harness_toolset


@dataclass
class HarnessAgent(AbstractCapability[AgentDepsT]):
    """A CLI session - one of the coding CLIs - as the agent's working backend.

    See the package `README.md` for why the session is the CLI's own, kept
    beside the work, and why its approval is one decision per prompt.
    """

    harness: Harness = "claude_code"
    access: Access = "read_only"
    model: str | None = None
    model_vendor: str | None = None
    base_url: str | None = None
    timeout_seconds: int = 30 * 60
    # Unsealed from the vault by the factory; `repr=False` for the reason
    # `ImageGeneration.api_key` gives - a repr reaches log lines and tracebacks.
    api_key: SecretStr | None = field(default=None, repr=False)
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
            f"This agent is backed by a harness session - {label} in its sandbox - "
            f"that does its work: it {reach}. Start one session per line of work "
            "with harness_start, keep prompting it with harness_prompt, and close "
            "it with harness_stop when the work is done; use harness_sessions when "
            "it is no longer clear which sessions are open. The session is the "
            "agent with the tools, and a person watches it work. Give it the whole "
            "task in the prompt: the goal, the files or area it concerns, "
            "constraints, and how to check the result. The session remembers what "
            "its earlier prompts read and changed, so follow up in the same "
            "session rather than starting over. Answer the person from the "
            "session's answer."
        )

    def get_toolset(self) -> AbstractToolset[Any]:
        if self._toolset is None:
            self._toolset = build_harness_toolset(
                harness=self.harness,
                access=self.access,
                model=self.model,
                model_vendor=self.model_vendor,
                base_url=self.base_url,
                api_key=self.api_key.get_secret_value() if self.api_key is not None else None,
                timeout_seconds=self.timeout_seconds,
            )
        return self._toolset
