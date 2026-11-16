"""Claude Code or Codex, working in the agent's sandbox at the model's request."""

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.coding_agent._harness import LABELS, Access, Harness
from app.agents.capabilities.coding_agent._personal import PersonalCodingExecutor
from app.agents.capabilities.coding_agent._toolset import RunsOn, SignIn, build_coding_toolset

LOCAL_CODING_PREFERENCES = "coding_agent.local_preferences"


@dataclass(frozen=True)
class CodingPreferences:
    """Session choices resolved from the initiating person's local chat controls."""

    model: str | None = None
    effort: str | None = None


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
    effort: str | None = None
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
    runs_on: RunsOn = "sandbox"
    personal_executor: PersonalCodingExecutor | None = field(default=None, repr=False)
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
        where = (
            "on the person's own computer, in the folder they chose"
            if self.runs_on == "this_computer"
            else "in an isolated task using the initiating person's profile account"
            if self.runs_on == "personal_sandbox"
            else "in your sandbox"
        )
        continuation = (
            "Each personal cloud task starts in an isolated copy. Review its diff and result archive; "
            "it does not apply changes to shared project files. Personal accounts do not run unattended schedules."
            if self.runs_on == "personal_sandbox"
            else "Each task names a session (`main` when it names none): the same name continues "
            "that session's earlier work and a new name opens another."
        )
        if self.runs_on == "this_computer":
            continuation += (
                " Each session may choose `harness` - Claude Code or Codex, signed in on that "
                "computer - and a `folder` inside the chat's folder, so several projects or "
                "both coding agents can work at once. Use distinct session names. A mid-run "
                "correction prefixed with [session:api] targets api; unaddressed corrections "
                "stay with you when several sessions are active."
            )
        elif self.runs_on == "sandbox":
            continuation += (
                " Sandbox tasks in this toolset queue so their workspace snapshots do not "
                "overlap. Named sessions keep separate histories, not separate files."
            )
        return (
            f"You can hand software work to {label}, a coding agent that works {where}: it {reach}. Use run_coding_agent with the whole task, then tell "
            "the person what it found or did. " + continuation
        )

    def get_toolset(self) -> AbstractToolset[Any]:
        if self._toolset is None:
            self._toolset = build_coding_toolset(
                harness=self.harness,
                access=self.access,
                model=self.model,
                effort=self.effort,
                base_url=self.base_url,
                api_key=self.api_key,
                sign_in=self.sign_in,
                shared_sandbox=self.shared_sandbox,
                runs_on=self.runs_on,
                personal_executor=self.personal_executor,
                timeout_seconds=self.timeout_seconds,
            )
        return self._toolset
