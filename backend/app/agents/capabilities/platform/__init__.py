"""Platform capability - the in-app assistant's hands (#1798)."""

from typing import Any

from pydantic import SecretStr

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.platform._capability import PlatformOperations
from app.agents.capabilities.platform._toolset import refused
from app.services.platform_mcp import PlatformApi, platform_tools

__all__ = ["PLATFORM_CAPABILITY_ID", "PLATFORM_CREDENTIAL_RESOURCE", "PlatformOperations"]

PLATFORM_CAPABILITY_ID = "platform"

PLATFORM_CREDENTIAL_RESOURCE = "platform_credential"
"""The credential minted for the person a run acts for, a `SecretStr`.

A resource rather than a secret binding because no operator chooses it: the
runner mints it from the run's own authorization, so it can never carry more
than the person does."""


async def _never_called(scope: Any, receive: Any, send: Any) -> None:
    raise RuntimeError("declaring the platform tools calls nothing")  # pragma: no cover


def _declared() -> tuple[CapabilityToolInfo, ...]:
    """The tools as the Builder lists them, read off the functions themselves."""
    tools = platform_tools(PlatformApi(_never_called, token=lambda: None, on_refusal=refused))
    return tuple(
        CapabilityToolInfo(id=tool.name, description=tool.summary, side_effecting=tool.writes)
        for tool in tools
    )


@register(
    id=PLATFORM_CAPABILITY_ID,
    name="Operate the platform",
    category="utility",
    description=(
        "Find agents, runs, knowledge bases, skills and members, and - with a "
        "person's approval - create agents and knowledge bases, add documents and "
        "invite people, as whoever the agent is acting for."
    ),
    tools=_declared(),
)
def _build(ctx: CapabilityBuildContext) -> PlatformOperations | None:
    credential = ctx.resources.get(PLATFORM_CREDENTIAL_RESOURCE)
    # Nobody to act for - an anonymous visitor on a public surface - is nobody
    # whose authority the tools could carry, so the agent simply has none.
    if not isinstance(credential, SecretStr):
        return None
    return PlatformOperations(credential=credential)
