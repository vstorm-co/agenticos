"""Connecting a personal service at the moment the agent reaches for it.

A personal MCP binding speaks as whoever is talking, so a person who has not
connected their own account has no tools for that service. Saying so before
every answer - a card under each message - asks for a connection the agent may
never need. Where somebody is watching the run, the service is offered to the
model as `connect_account` instead: the run pauses on the call, the chat asks
the person to connect, and once they have, the service's tools join the same
run from its next step.

Deliberately not a registry capability, for the reason `ask_user` is not: it is
not a property of the agent but of the surface. Only one that can hold a run
open while somebody signs in can offer it; every other surface keeps briefing
the model that the service is unavailable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import (
    AbstractToolset,
    CombinedToolset,
    DynamicToolset,
    FunctionToolset,
    ToolsetFunc,
)

from app.agents.capabilities._failures import steer
from app.agents.deps import AgentDeps
from app.agents.mcp import tool_prefix

OwnAccountGap = Literal["not_connected", "undecided", "unauthorized"]
"""Why a signed-in person's own account on a service cannot be used - each one
something they can put right while the run waits."""

ServiceOutcome = AbstractToolset[Any] | OwnAccountGap | Literal["unreachable"]
"""The service read again after the person said they connected it: its toolset,
the gap that still stands, or `"unreachable"` for a connection whose server did
not answer."""


@dataclass(frozen=True)
class ConnectionRequest:
    """What the surface shows while the run waits: which service, and what is wrong."""

    catalog_key: str
    name: str
    gap: OwnAccountGap


ConnectionCallback = Callable[[ConnectionRequest], Awaitable[bool]]
"""Put the request to the person and wait. True once they say they connected,
False when they skip it or are no longer there to answer."""


@dataclass(frozen=True)
class PendingService:
    """One personal service this run may connect, and how to reach it afterwards."""

    request: ConnectionRequest
    # Read again rather than remembered: the connection the person just made is
    # a row this run's own transaction has never seen.
    resolve: Callable[[], Awaitable[ServiceOutcome]]


_WHY = {
    "not_connected": "they have not connected it",
    "undecided": "they hold several connections to it and none is marked as the one agents use",
    "unauthorized": "their connection to it no longer authorizes",
}

_STILL = {
    "not_connected": "is still not connected - the sign-in may not have finished",
    "undecided": (
        "still has several connections with none marked as the one agents use - "
        "they mark one as default on the MCP servers page, under You"
    ),
    "unauthorized": (
        "still does not authorize - they authorize it again on the MCP servers page, under You"
    ),
    "unreachable": "is connected, but its server did not answer",
}


@dataclass
class ConnectOnUse(AbstractCapability[AgentDeps]):
    """`connect_account`, and a slot per service for the tools it attaches."""

    services: Sequence[PendingService]
    request_connection: ConnectionCallback = field(repr=False, compare=False)

    _attached: dict[str, AbstractToolset[Any]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    # Skipped once, not asked again this run: a model that retries the call
    # would otherwise put the same card up after every "no".
    _declined: set[str] = field(default_factory=set, init=False, repr=False, compare=False)

    def get_instructions(self) -> str:
        """One paragraph per service, telling the model to connect it when needed."""
        return "\n\n".join(
            f"{req.name} is bound to the account of whoever is talking to you, and it is not "
            f"available to them yet: {_WHY[req.gap]}. Do not raise it up front. When a request "
            f'needs {req.name}, call `connect_account` with service="{req.catalog_key}" - it '
            f"asks them to connect it and waits, and once they have, the {req.name} tools are "
            "yours from your next step."
            for req in (service.request for service in self.services)
        )

    def get_toolset(self) -> AbstractToolset[AgentDeps]:
        """The tool, plus one slot per service that stays empty until it is attached.

        A slot per service rather than one combined set rebuilt on each attach:
        the slot is re-read every step and compared by identity, so a rebuilt set
        would close and reopen every server already attached. What each slot
        holds lives on this instance, so building the set again changes nothing.
        """
        connect: FunctionToolset[AgentDeps] = FunctionToolset()
        connect.add_function(self._connect_account, name="connect_account", takes_ctx=True)
        parts: list[AbstractToolset[AgentDeps]] = [connect]
        parts.extend(
            DynamicToolset(self._slot(service.request.catalog_key), per_run_step=True)
            for service in self.services
        )
        return CombinedToolset[AgentDeps](parts)

    def _slot(self, key: str) -> ToolsetFunc[AgentDeps]:
        def attached(_ctx: RunContext[AgentDeps]) -> AbstractToolset[Any] | None:
            return self._attached.get(key)

        return attached

    async def _connect_account(self, ctx: RunContext[AgentDeps], service: str) -> str:
        """Ask the person to connect one of their own services, and wait until they have.

        Call it only when the request in front of you needs that service. Once it
        is connected, its tools are available from your next step.

        Args:
            service: The service's key, as your instructions name it.
        """
        pending = next((one for one in self.services if one.request.catalog_key == service), None)
        if pending is None:
            keys = ", ".join(f'"{one.request.catalog_key}"' for one in self.services)
            return steer(ctx, f"There is no service {service!r} to connect. Use one of: {keys}.")
        name = pending.request.name
        if service in self._attached:
            return f"{name} is already connected; its tools are available."
        if service in self._declined:
            return f"They chose not to connect {name} earlier in this turn. Carry on without it."
        if not await self.request_connection(pending.request):
            self._declined.add(service)
            return (
                f"They did not connect {name}, so its tools are not available. Carry on "
                f"without it and say plainly what you could not do."
            )
        outcome = await pending.resolve()
        if isinstance(outcome, str):
            return (
                f"Their {name} {_STILL[outcome]}, so its tools are not available. Tell them, "
                "and that they can ask again once it is sorted."
            )
        self._attached[service] = outcome
        return (
            f"{name} is connected. Its tools, named `{tool_prefix(service)}_...`, are available "
            "from your next step."
        )
