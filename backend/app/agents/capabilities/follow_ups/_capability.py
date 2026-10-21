"""Next steps the person can take with one click."""

from dataclasses import dataclass, field

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT

from app.agents.capabilities.follow_ups._toolset import FollowUpsToolset


@dataclass
class FollowUps(AbstractCapability[AgentDepsT]):
    """Lets an agent end a turn with buttons for what to do next (#2301).

    A paragraph of "Would you like me to..." at the end of every answer is the
    habit people complain about most, and a newcomer who does not know what to
    ask next reads straight past it. As buttons the same suggestions cost one
    click, and the answer above them stays the answer.

    ```python
    from pydantic_ai import Agent
    from app.agents.capabilities.follow_ups import FollowUps

    agent = Agent('openai:gpt-4.1', capabilities=[FollowUps()])
    ```
    """

    _toolset: FollowUpsToolset[AgentDepsT] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> FollowUpsToolset[AgentDepsT]:
        """The follow-ups toolset, built once per capability instance."""
        if self._toolset is None:
            self._toolset = FollowUpsToolset[AgentDepsT]()
        return self._toolset
