"""The model chooses a task, never a program, arguments or account."""

from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._failures import steer
from app.agents.capabilities.coding_agent._task import MAIN_SESSION, SESSION_NAME
from app.agents.capabilities.coding_agent._toolset import run_local_task
from app.agents.deps import AgentDeps

RUN_DESCRIPTION = "Hand a task to the external ACP agent registered on this computer."


def build_acp_toolset(agent_id: str, timeout_seconds: int) -> FunctionToolset[AgentDeps]:
    async def run_acp_agent(
        ctx: RunContext[AgentDeps],
        task: str,
        session: str = MAIN_SESSION,
        fresh_session: bool = False,
        folder: str | None = None,
    ) -> str:
        """Hand a task to the external ACP agent registered on this computer.

        Use for whole tasks with a goal, constraints and a way to verify the result.
        The program uses its own login and tools with local account access.

        Args:
            task: The complete task; this agent sees it and its own session history.
            session: Up to 40 lower-case letters, digits, hyphens or underscores.
                The same name continues earlier work; a new name starts independent work.
            fresh_session: Start this named session over instead of resuming it.
            folder: A folder inside the chat's approved folder. Empty uses the chat's folder.

        Returns:
            JSON with outcome, answer, steps and files_changed, or an explicit refusal.
            Use answer to explain the result; a failure does not mean no work occurred.
        """
        if not SESSION_NAME.fullmatch(session):
            return steer(
                ctx,
                "Use a session name of up to 40 lower-case letters, digits, hyphens or underscores, starting with a letter or digit.",
            )
        return await run_local_task(
            ctx,
            task,
            session,
            fresh_session,
            "custom",
            folder,
            access="edit",
            timeout_seconds=timeout_seconds,
            custom_agent_id=agent_id,
        )

    return FunctionToolset([run_acp_agent])
