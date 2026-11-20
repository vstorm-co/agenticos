"""The author opts into one agent talking to another, in the open."""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities.agent_messages._toolset import build_agent_messages_toolset
from app.agents.deps import AgentDeps


@dataclass
class AgentMessages(AbstractCapability[AgentDeps]):
    max_message_chars: int = 16_000
    allow_attachments: bool = True

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        return build_agent_messages_toolset(
            max_message_chars=self.max_message_chars,
            allow_attachments=self.allow_attachments,
        )

    def get_instructions(self) -> Callable[[RunContext[AgentDeps]], str]:
        return self._instructions

    def _instructions(self, ctx: RunContext[AgentDeps]) -> str:
        return (
            "You may message another agent with agent_send_message, addressed by "
            "its slug or id, and read what it wrote back with agent_list_threads "
            "and agent_read_messages. A message is stored in the thread the two of "
            "you share; it does not start a run of the other agent, and it does not "
            "wake it up. Say what the other agent needs to act on, and no more: "
            "the thread is visible in the console to anyone who may run either "
            "agent. Use agent_react for a one-emoji acknowledgement rather than a "
            "message. Never send a credential, a secret, or anything the other "
            "agent's readers should not see."
        )
