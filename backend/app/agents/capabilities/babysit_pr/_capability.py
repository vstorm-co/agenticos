"""Watch a pull request through CI, reporting only what changed (#7).

The watcher holds one watch per run: the agent hands it a snapshot
of the PR's checks whenever the monitor wakes it, and the watcher
says what changed and what to do next. The capability never runs
`gh` itself and never touches the PR — no merge, no comment, no
other action. Reading the checks is the agent's job (`gh pr
checks` under the monitor capability); classifying them is this
capability's.
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.babysit_pr import (
    DEFAULT_MAX_WATCH_MINUTES,
    DEFAULT_POLL_SECONDS,
    BabysitWatcher,
)
from app.agents.capabilities.babysit_pr._toolset import build_babysit_pr_toolset
from app.agents.manifest import RunRecorder

#: The run's recorder, so watch events land on the manifest beside
#: the requests. Read here rather than resolved here: the runner
#: holds the recorder, and a capability must never fetch run state
#: itself.
BABYSIT_PR_RECORDER_RESOURCE = "babysit_pr_recorder"

_INSTRUCTIONS = (
    "Babysit one pull request through CI with the babysit_pr tools. "
    "Watch it with the monitor capability — start_monitor on "
    "`gh pr checks --watch` — and hand each new snapshot to "
    "babysit_pr_check with the repo, PR number, head SHA, and the "
    "checks as reported. Report only what the tool reports as "
    "changed; when its report is empty, end your turn without a "
    "message, never post or say 'still waiting'. Stop with "
    "babysit_pr_stop when the tool says green on the latest commit, "
    "when the PR is blocked, or when you ask the user a question. "
    "Before watching again, check `gh api rate_limit` and pass what "
    "it says to babysit_pr_rate_limit. Only the thread that owns the "
    "PR watches it: a delegated child never watches. Never merge, "
    "comment, or take any other action on the PR yourself — watching "
    "and reporting only."
)


@dataclass
class BabysitPr(AbstractCapability[AgentDepsT]):
    """Watches one PR's checks and reports only what changed."""

    watcher: BabysitWatcher = field(default_factory=BabysitWatcher)
    recorder: RunRecorder = field(default_factory=RunRecorder)
    poll_interval_seconds: int = DEFAULT_POLL_SECONDS
    max_watch_minutes: int = DEFAULT_MAX_WATCH_MINUTES

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        """The babysit-pr tools, built once."""
        if self._toolset is None:
            self._toolset = build_babysit_pr_toolset(
                self.watcher,
                self.recorder,
                self.poll_interval_seconds,
                self.max_watch_minutes,
            )
        return self._toolset

    def get_instructions(self) -> str:
        """How babysitting works, in the agent's instructions."""
        return _INSTRUCTIONS
