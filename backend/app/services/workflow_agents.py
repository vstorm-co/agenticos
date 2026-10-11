"""The agent a workflow's `agent.run` step configures in place, rather than picks.

Such an agent is still an agent: a row with published versions, run through
`AgentRunnerService` like any other, with its budget, approvals, guardrails and
run history. What makes it the step's is `workflow_id` and `workflow_node_id` -
the workflow owns it, so it stays out of the catalog, is reached through the
workflow's access, and goes when the workflow does.

Its spec lives in the step's configuration and is versioned with the graph. The
step's first run creates the agent; a run whose spec differs from the newest
version publishes a new one first, checked exactly as publishing an agent is,
against the access of whoever the run acts as. An unchanged spec reuses its
version, so a step that runs a thousand times publishes once.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import SPEC_VERSION, AgentSpec
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.db.locks import LockScope, hold_subject
from app.db.models.agent import Agent, AgentStatus
from app.db.models.resource_grant import Visibility
from app.repositories import agent_repo
from app.services.agent_registry import AgentRegistryService


def _frozen(spec: AgentSpec) -> dict[str, object]:
    """The spec as a version stores it - stamped with this deployment's spec version,
    as `AgentRegistryService.publish` stamps one - so equal specs compare equal."""
    return spec.model_copy(update={"spec_version": SPEC_VERSION}).model_dump(mode="json")


class WorkflowAgentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)

    async def problems(self, ctx: AuthContext, spec: AgentSpec) -> list[str]:
        """What stops this spec from being published, in the publish check's words."""
        try:
            await self.registry.validate_spec(ctx, spec)
        except BadRequestError as exc:
            return [str(problem) for problem in (exc.details or {}).get("problems", [exc.message])]
        return []

    async def version_for(
        self, ctx: AuthContext, *, workflow_id: UUID, node_id: UUID, spec: AgentSpec
    ) -> tuple[UUID, UUID]:
        """The agent and version that run this step's spec, publishing it first if it changed.

        Raises:
            BadRequestError: The spec cannot be published for this caller - a model,
                collection or server they may not use, or a broken reference.
        """
        await hold_subject(self.db, LockScope.WORKFLOW_STEP_AGENT, node_id)
        organization_id = ctx.organization_id
        frozen = _frozen(spec)
        agent = await agent_repo.get_for_workflow_node(
            self.db, workflow_id=workflow_id, node_id=node_id, organization_id=organization_id
        )
        if agent is not None:
            newest = await agent_repo.newest_version(
                self.db, agent_id=agent.id, organization_id=organization_id
            )
            if newest is not None and newest.spec == frozen:
                return agent.id, newest.id
        await self.registry.validate_spec(ctx, spec, agent_id=agent.id if agent else None)
        if agent is None:
            agent = await self._create(ctx, workflow_id=workflow_id, node_id=node_id, spec=spec)
        number = await agent_repo.next_version_number(self.db, agent_id=agent.id)
        version = await agent_repo.create_version(
            self.db,
            agent_id=agent.id,
            organization_id=organization_id,
            version=number,
            spec=frozen,
            note="Published by its workflow step",
            published_by_user_id=ctx.user_id,
        )
        await agent_repo.update(
            self.db,
            agent=agent,
            update_data={
                "name": spec.name,
                "description": spec.description,
                "draft_spec": frozen,
                "status": AgentStatus.PUBLISHED.value,
                "current_version_id": version.id,
            },
        )
        return agent.id, version.id

    async def _create(
        self, ctx: AuthContext, *, workflow_id: UUID, node_id: UUID, spec: AgentSpec
    ) -> Agent:
        return await agent_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            # Unique per workflow and step, and never a catalog agent's: no catalog
            # slug starts with a workflow's id.
            slug=f"wf-{workflow_id.hex[:12]}-{node_id.hex[:12]}",
            name=spec.name,
            description=spec.description,
            draft_spec=_frozen(spec),
            # Nobody's: the workflow's access is what reaches it.
            owner_user_id=None,
            created_by_user_id=ctx.user_id,
            visibility=Visibility.PRIVATE.value,
            categories=[],
            tags=[],
            workflow_id=workflow_id,
            workflow_node_id=node_id,
        )
