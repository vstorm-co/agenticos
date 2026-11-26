"""What a person deciding a parked call of the platform's own tools reads on its card.

A platform tool's arguments are ids, a hash and flags. Each describer here reads the
records they name as the run's person, through the same service checks a console read
takes, and answers names: the agent, the attempt and its verdict, the version a
publish makes. As with a capability's describer, `None` - a record gone, or one the
person may not read - parks the call with its raw arguments, because a description is
a courtesy and the approval is not.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.deps import AgentDeps
from app.agents.mcp import PLATFORM_MCP_NAME
from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.session import get_db_context
from app.services.access import acting_member

type PlatformDescriber = Callable[[AgentDeps, Mapping[str, Any]], Awaitable[dict[str, str] | None]]
type _Read = Callable[[AsyncSession, AuthContext, Mapping[str, Any]], Awaitable[dict[str, str]]]


def _id(value: object) -> UUID:
    return UUID(str(value))


async def _accept_improvement(
    db: AsyncSession, ctx: AuthContext, args: Mapping[str, Any]
) -> dict[str, str]:
    # Imported here: the services reach the agent capabilities this module serves.
    from app.services.agent_registry import AgentRegistryService
    from app.services.improvement_pipeline import ImprovementPipelineService

    agent = await AgentRegistryService(db).get(ctx, _id(args["agent_id"]))
    session = await ImprovementPipelineService(db).read(ctx, agent.id, _id(args["session_id"]))
    # The attempt the call names, which the server holds the acceptance to.
    number = int(args["attempt"])
    attempt = next((item for item in session.iterations if item.number == number), None)
    if attempt is None:
        raise KeyError("attempt")
    return {
        "agent": agent.name,
        "attempt": str(number),
        "verdict": "" if attempt.verdict is None else str(attempt.verdict.value),
        "publish": "yes" if args.get("publish") is True else "no",
    }


async def _publish_agent(
    db: AsyncSession, ctx: AuthContext, args: Mapping[str, Any]
) -> dict[str, str]:
    # Imported here: the services reach the agent capabilities this module serves.
    from app.services.agent_registry import AgentRegistryService

    # No version number: a publish takes the next one when it runs, not when it parks.
    agent = await AgentRegistryService(db).get(ctx, _id(args["agent_id"]))
    return {"agent": agent.name}


async def _change_skill_version(
    db: AsyncSession, ctx: AuthContext, args: Mapping[str, Any]
) -> dict[str, str]:
    # Imported here: the services reach the agent capabilities this module serves.
    from app.repositories import skill_version as skill_version_repo
    from app.services.agent_registry import AgentRegistryService
    from app.services.skills import SkillService

    skill = await SkillService(db).get(ctx, _id(args["skill_id"]))
    agent = await AgentRegistryService(db).get(ctx, _id(args["agent_id"]))
    state = str(args.get("state", ""))
    described = {"skill": skill.name, "agent": agent.name, "state": state}
    if state == "pinned":
        described["version"] = str(int(args["version"]))
    elif state == "fork":
        fork = await skill_version_repo.get_fork(
            db, _id(args["fork_id"]), organization_id=ctx.organization_id, skill_id=skill.id
        )
        if fork is None:
            raise KeyError("fork_id")
        described["fork"] = fork.name
    return described


async def _accept_skill_improvement(
    db: AsyncSession, ctx: AuthContext, args: Mapping[str, Any]
) -> dict[str, str]:
    # Imported here: the services reach the agent capabilities this module serves.
    from app.services.agent_registry import AgentRegistryService
    from app.services.skills import SkillService

    skill = await SkillService(db).get(ctx, _id(args["skill_id"]))
    outcome = str(args.get("outcome", ""))
    chosen = args.get("fork_agent_ids") or []
    if outcome != "fork_for_helped" or not chosen:
        return {"skill": skill.name, "outcome": outcome}
    # Named agents move instead of the helped ones, so the card names exactly them.
    registry = AgentRegistryService(db)
    names = [(await registry.get(ctx, _id(agent_id))).name for agent_id in chosen]
    return {"skill": skill.name, "outcome": "fork_for_chosen", "agents": ", ".join(names)}


async def _start_eval_run(
    db: AsyncSession, ctx: AuthContext, args: Mapping[str, Any]
) -> dict[str, str]:
    # Imported here: the services reach the agent capabilities this module serves.
    from app.services.agent_registry import AgentRegistryService
    from app.services.dataset import DatasetService

    run = args["run"]
    run = run.model_dump(mode="json") if hasattr(run, "model_dump") else run
    agent = await AgentRegistryService(db).get(ctx, _id(args["agent_id"]))
    dataset = await DatasetService(db).get(ctx, _id(run["dataset_id"]))
    version = run.get("dataset_version")
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

    async def describe(deps: AgentDeps, args: Mapping[str, Any]) -> dict[str, str] | None:
        person = None if deps.run_person is None else str(deps.run_person)
        async with get_db_context() as db:
            ctx = await acting_member(db, deps.organization_id, person)
            if ctx is None:
                return None
            try:
                return await read(db, ctx, args)
            except AppException, KeyError, TypeError, ValueError:
                return None

    return describe
