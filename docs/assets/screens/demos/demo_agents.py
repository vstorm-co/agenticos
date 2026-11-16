"""The Northwind Labs agents the demo seeds in this folder build on.

A seed creates the ones it is missing, so a fresh deployment needs only
`agenticos cmd bootstrap --org "Northwind Labs"` before it runs: that makes the
organization, its owner and the Architect. An agent that already exists under
the name is used as it is.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.resource_grant import Visibility
from app.services.agent_registry import AgentRegistryService

ORGANIZATION = "Northwind Labs"
BOOTSTRAP = f'agenticos cmd bootstrap --org "{ORGANIZATION}"'

_ROLES = {
    "Visuals Lab": "Turns tables and notes into charts and interactive Apps.",
    "Finance Analyst": "Reads catalogs, prices and margins and says what they add up to.",
    "Support Desk": "Answers customer questions from the published policies.",
    "Chief of Staff": "Keeps the weekly brief: decisions, owners and open risks.",
    "Onboarding Buddy": "Shows a new teammate where the company's knowledge lives.",
    "Sales Researcher": "Researches accounts and reviews the revenue workflow.",
    "Tech Lead": "Writes technical handovers and keeps assumptions visible.",
}


async def ensure_agent(
    db: AsyncSession, ctx: AuthContext, name: str, *, model_profile_id: UUID | None
) -> Agent:
    """The organization's agent called `name`, created when it has none.

    Published on `model_profile_id` when one is given; a draft otherwise, which
    is all an App or a prepared conversation needs. The Architect is not one
    a seed makes: bootstrap installs it.
    """
    found = await db.scalar(
        select(Agent).where(Agent.organization_id == ctx.organization_id, Agent.name == name)
    )
    if found is not None:
        return found
    if name not in _ROLES:
        raise ValueError(f"The demo organization needs {name} - run `{BOOTSTRAP}` first")
    spec = AgentSpec(
        name=name,
        description=_ROLES[name],
        instructions=f"{_ROLES[name]} This is a fictional demonstration organization.",
        model_profile_id=model_profile_id,
        capabilities=([CapabilityBindingSpec(id="visuals")] if name == "Visuals Lab" else []),
    )
    registry = AgentRegistryService(db)
    agent = await registry.create(
        ctx, spec, choose_model=False, visibility=Visibility.ORG, tags=["demo"]
    )
    if model_profile_id is not None:
        await registry.publish(ctx, agent.id, note="Northwind Labs demo agent")
    return agent
