"""Small task controls; identity, versions and authority never come from the model."""

from typing import Annotated
from uuid import UUID

from pydantic import Field
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.deps import AgentDeps
from app.core.exceptions import AppException
from app.db.session import get_db_context
from app.schemas.conversation_task import StartConversationTask
from app.schemas.local_target import LocalTarget
from app.services.access import acting_member
from app.services.conversation_tasks import ConversationTaskService

START_DESCRIPTION = "Start a fresh topic in the background and return immediately while this conversation continues."
LIST_DESCRIPTION = (
    "Read this conversation's background topics, their status and where to open them."
)
STOP_DESCRIPTION = "Stop a background topic started from this conversation."


def build_background_tasks_toolset(
    *, local: LocalTarget | None, model_profile_id: UUID | None = None
) -> FunctionToolset[AgentDeps]:
    toolset: FunctionToolset[AgentDeps] = FunctionToolset()

    async def start_background_task(
        ctx: RunContext[AgentDeps],
        title: Annotated[str, Field(min_length=1, max_length=160)],
        prompt: Annotated[str, Field(min_length=1, max_length=16000)],
        agent_id: UUID | None = None,
    ) -> str:
        """Start a fresh topic in the background and return immediately while this conversation continues.

        Use when the person wants independent work without holding up this topic.
        For coding, ask the topic to use its coding harness. It retains this agent's
        tools, budgets and approval rules; no approval is waived. A local task stays
        on this exact computer and folder. Only four tasks may be active per person.

        Args:
            title: A short name for the new topic, e.g. 'Investigate the export bug'.
            prompt: The complete brief: goal, relevant facts, constraints and expected result.
                The new topic starts with fresh context, without this transcript.
            agent_id: A published delegate pinned by this agent, or empty for this agent.

        Returns:
            JSON with task id, fresh conversation id and queued status. Completion
            returns here automatically, including after an approval. A refusal is
            text explaining why; it has not started any work.
        """
        deps = ctx.deps
        if (
            deps.run_id is None
            or deps.conversation_id is None
            or ctx.tool_call_id is None
            or deps.impersonated
        ):
            return "Background topics need a signed-in person's published console conversation."
        try:
            async with get_db_context() as db:
                auth = await acting_member(db, deps.organization_id, deps.user_id)
                if auth is None or deps.run_person != auth.subject_id:
                    return "Background topics need an active organization member."
                task = await ConversationTaskService(db).start(
                    auth,
                    source_run_id=deps.run_id,
                    tool_call_id=ctx.tool_call_id,
                    request=StartConversationTask(title=title, prompt=prompt, agent_id=agent_id),
                    local=local,
                    model_profile_id=model_profile_id,
                )
                return task.model_dump_json()
        except AppException as exc:
            return f"Refused ({exc.code}): {exc.message}"

    async def list_background_tasks(ctx: RunContext[AgentDeps]) -> str:
        """Read this conversation's background topics, their status and where to open them.

        Use on the person's request, or to check one task once; do not poll in a loop.

        Returns:
            JSON with up to fifty newest topics, including each task's id, title,
            status and conversation id. Only tasks this member started here are included.
        """
        if ctx.deps.conversation_id is None:
            return "No source conversation is available."
        try:
            async with get_db_context() as db:
                auth = await acting_member(db, ctx.deps.organization_id, ctx.deps.user_id)
                if auth is None:
                    return "Background topics need an active organization member."
                tasks = await ConversationTaskService(db).list_for_member(
                    auth, conversation_id=ctx.deps.conversation_id
                )
                return "[" + ",".join(task.model_dump_json() for task in tasks) + "]"
        except AppException as exc:
            return f"Refused ({exc.code}): {exc.message}"

    async def stop_background_task(ctx: RunContext[AgentDeps], task_id: UUID) -> str:
        """Stop a background topic started from this conversation.

        Args:
            task_id: The id returned by start_background_task or list_background_tasks.

        Returns:
            JSON with the cancelled task state. Stopping cannot undo completed file
            edits or other external actions. The topic keeps its transcript and spend.
        """
        try:
            async with get_db_context() as db:
                auth = await acting_member(db, ctx.deps.organization_id, ctx.deps.user_id)
                if auth is None:
                    return "Background topics need an active organization member."
                service = ConversationTaskService(db)
                task = await service.get(auth, task_id)
                if task.source_conversation_id != ctx.deps.conversation_id:
                    return "That task was not started from this conversation."
                return (await service.stop(auth, task_id)).model_dump_json()
        except AppException as exc:
            return f"Refused ({exc.code}): {exc.message}"

    toolset.add_function(start_background_task)
    toolset.add_function(list_background_tasks)
    toolset.add_function(stop_background_task)
    return toolset
