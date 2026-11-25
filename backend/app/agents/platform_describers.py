"""What a person deciding a parked call of the platform's own tools reads on its card.

A platform tool's arguments are ids, a hash and flags. Each describer here reads the
records they name as the run's person, through the same service checks a console read
takes, and answers names: the agent, the attempt and its verdict, the version a
publish makes. As with a capability's describer, `None` - a record gone, or one the
person may not read - parks the call with its raw arguments, because a description is
a courtesy and the approval is not.
"""

from collections.abc import Awaitable, Callable, Mapping
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.deps import AgentDeps
from app.agents.mcp import PLATFORM_MCP_NAME
from app.core.exceptions import AppException, AuthorizationError
from app.core.permissions import AuthContext, Perm
from app.db.session import get_db_context
from app.schemas.base import BaseSchema
from app.services.access import acting_member

type PlatformDescriber = Callable[
    [AgentDeps, Mapping[str, object]], Awaitable[dict[str, str] | None]
]
type _Read = Callable[[AsyncSession, AuthContext, Mapping[str, object]], Awaitable[dict[str, str]]]


_ID = TypeAdapter(UUID)


def _id(value: object) -> UUID:
    return _ID.validate_python(value)


class _EvalReference(BaseSchema):
    dataset_id: UUID
    dataset_version: int | None = None


async def _accept_improvement(
    db: AsyncSession, ctx: AuthContext, args: Mapping[str, object]
) -> dict[str, str]:
    # Imported here: the services reach the agent capabilities this module serves.
    from app.services.agent_registry import AgentRegistryService
    from app.services.improvement_pipeline import ImprovementPipelineService

    if not ctx.has(Perm.RUNS_VIEW):
        raise AuthorizationError(
            message="Reading an improvement session requires runs:view", details={}
        )
    agent = await AgentRegistryService(db).get(ctx, _id(args["agent_id"]))
    session = await ImprovementPipelineService(db).read(ctx, agent.id, _id(args["session_id"]))
    chosen = next(item for item in session.iterations if item.id == session.best_iteration_id)
    publishes = args.get("publish") is True and session.next_version is not None
    return {
        "agent": agent.name,
        "attempt": str(chosen.number),
        "verdict": "" if chosen.verdict is None else str(chosen.verdict.value),
        "publish": "yes" if publishes else "no",
        "version": str(session.next_version) if publishes else "",
    }


async def _publish_agent(
    db: AsyncSession, ctx: AuthContext, args: Mapping[str, object]
) -> dict[str, str]:
    # Imported here: the services reach the agent capabilities this module serves.
    from app.repositories import agent as agent_repo
    from app.services.agent_registry import AgentRegistryService

    agent = await AgentRegistryService(db).get(ctx, _id(args["agent_id"]))
    newest = await agent_repo.newest_version(
        db, agent_id=agent.id, organization_id=agent.organization_id
    )
    return {"agent": agent.name, "version": str(1 if newest is None else newest.version + 1)}


async def _change_skill_version(
    db: AsyncSession, ctx: AuthContext, args: Mapping[str, object]
) -> dict[str, str]:
    # Imported here: the services reach the agent capabilities this module serves.
    from app.services.agent_registry import AgentRegistryService
    from app.services.skills import SkillService

    skill = await SkillService(db).get(ctx, _id(args["skill_id"]))
    agent = await AgentRegistryService(db).get(ctx, _id(args["agent_id"]))
    version = args.get("version")
    return {
        "skill": skill.name,
        "agent": agent.name,
        "state": str(args.get("state", "")),
        "version": "" if version is None else str(version),
    }


async def _accept_skill_improvement(
    db: AsyncSession, ctx: AuthContext, args: Mapping[str, object]
) -> dict[str, str]:
    # Imported here: the services reach the agent capabilities this module serves.
    from app.services.skills import SkillService

    skill = await SkillService(db).get(ctx, _id(args["skill_id"]))
    return {"skill": skill.name, "outcome": str(args.get("outcome", ""))}


async def _start_eval_run(
    db: AsyncSession, ctx: AuthContext, args: Mapping[str, object]
) -> dict[str, str]:
    # Imported here: the services reach the agent capabilities this module serves.
    from app.services.agent_registry import AgentRegistryService
    from app.services.dataset import DatasetService

    run = _EvalReference.model_validate(args["run"])
    agent = await AgentRegistryService(db).get(ctx, _id(args["agent_id"]))
    dataset = await DatasetService(db).get(ctx, run.dataset_id)
    version = run.dataset_version
    return {
        "agent": agent.name,
        "dataset": dataset.name,
        "version": "" if version is None else str(version),
    }


_READS: dict[str, _Read] = {
    "accept_improvement": _accept_improvement,
    "publish_agent": _publish_agent,
    "change_skill_version": _change_skill_version,
    "accept_skill_improvement": _accept_skill_improvement,
    "start_eval_run": _start_eval_run,
}


def platform_describer(tool_name: str) -> PlatformDescriber | None:
    """The describer for a platform tool's effective name, or `None` for any other tool."""
    read = _READS.get(tool_name.removeprefix(f"{PLATFORM_MCP_NAME}_"))
    if read is None or not tool_name.startswith(f"{PLATFORM_MCP_NAME}_"):
        return None

    async def describe(deps: AgentDeps, args: Mapping[str, object]) -> dict[str, str] | None:
        person = None if deps.run_person is None else str(deps.run_person)
        async with get_db_context() as db:
            ctx = await acting_member(db, deps.organization_id, person)
            if ctx is None:
                return None
            try:
                return await read(db, ctx, args)
            except AppException, KeyError, StopIteration, ValueError:
                return None

    return describe
