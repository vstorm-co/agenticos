"""Asking for the person's computer at the moment the agent needs it.

An agent whose workspace is the person's own computer has nothing to work in
until they choose a folder or the whole computer in the desktop app. Refusing
the whole turn for that - "choose a folder first" before a question that never
needed a file - made such an agent unusable for anything else. Where somebody is
at the keyboard, the run starts without the workspace and the model is offered
`request_computer_access` instead: the run pauses on the call, the app asks
the person where the agent may work, and the turn ends so the next one opens
with the folder they chose.

Not a registry capability, for the reason `connect_account` is not: it belongs
to the surface. Only a chat someone is watching can wait for a choice made in a
native dialog; every other surface keeps refusing the run up front.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from app.agents.deps import AgentDeps

REQUEST_COMPUTER_ACCESS = "request_computer_access"
"""The tool's name, which the approval gate leaves ungated where this is attached."""


@dataclass(frozen=True)
class ComputerAccessRequest:
    """What the app shows while the run waits."""

    reason: str
    coding: bool = False


ComputerAccessCallback = Callable[[ComputerAccessRequest], Awaitable[bool]]
"""Put the request to the person and wait. True once they granted a folder or the
whole computer, False when they declined or are no longer there to answer."""

_INSTRUCTIONS = (
    "You work on the files and shell of the person's own computer, but they have not "
    "given this chat a folder or the whole computer yet, so you have no file or shell "
    "tools this turn. Do not raise it up front: answer whatever needs no files. When a "
    "request needs their files or a command, call `request_computer_access` with a short "
    "reason. It asks them where you may work and waits."
)


@dataclass
class RequestComputerOnUse(AbstractCapability[AgentDeps]):
    """`request_computer_access`, for a run whose computer has not been granted yet."""

    request_access: ComputerAccessCallback = field(repr=False, compare=False)
    coding: bool = False

    _granted: bool = field(default=False, init=False, repr=False, compare=False)
    # Declined once, not asked again this turn: a model that retries the call
    # would otherwise put the dialog up after every "no".
    _declined: bool = field(default=False, init=False, repr=False, compare=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def get_instructions(self) -> str:
        """Tell the model the computer is there to ask for, not to announce."""
        return _INSTRUCTIONS

    def get_toolset(self) -> AbstractToolset[AgentDeps]:
        """The one tool."""
        tools: FunctionToolset[AgentDeps] = FunctionToolset()
        tools.add_function(self._request, name=REQUEST_COMPUTER_ACCESS, takes_ctx=True)
        return tools

    async def _request(self, ctx: RunContext[AgentDeps], reason: str) -> str:
        """Ask the person where you may work on their computer, and wait for the answer.

        Call it only when the request in front of you needs their files or a
        command. Once they choose a folder or the whole computer, their app starts
        the next turn with it.

        Args:
            reason: One short sentence on what you need the files for.
        """
        del ctx
        async with self._lock:
            if self._granted:
                return (
                    "They already granted access this turn. End the turn now; the next "
                    "one starts with their files."
                )
            if self._declined:
                return "They declined earlier in this turn. Carry on without their files."
            if not await self.request_access(
                ComputerAccessRequest(reason=reason.strip(), coding=self.coding)
            ):
                self._declined = True
                return (
                    "They did not grant access to their computer, so you have no files or "
                    "shell. Carry on without them and say plainly what you could not do."
                )
            self._granted = True
            return (
                "They granted access. Their app starts the next turn with the folder they "
                "chose, so end this turn now with one short sentence saying you are "
                "continuing with their files. Do not answer the request yet."
            )
