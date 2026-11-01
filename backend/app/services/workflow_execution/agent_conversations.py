"""Private, durable histories for agent steps, separate from workflow result delivery."""

from dataclasses import dataclass
from uuid import UUID, uuid5

from pydantic_ai.messages import ModelMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories import conversation as conversation_repo
from app.services.conversation import API_HISTORY_MESSAGES, ConversationService
from app.services.workflow_execution.context import DispatchContext

_NAMESPACE = UUID("cc293fe2-ad7d-4270-a2ed-69699035347f")


@dataclass(frozen=True)
class AgentConversation:
    id: UUID
    history: list[ModelMessage]


def conversation_key(current: DispatchContext, agent_id: UUID, version_id: UUID) -> UUID:
    """A client token selects only a namespaced test thread, never a real chat row."""
    if current.nested:
        kind, subject = "invocation", current.node_run_id
    elif current.source_conversation_id is not None:
        kind, subject = "chat", current.source_conversation_id
    elif current.test_chat_key is not None:
        kind, subject = "test", current.test_chat_key
    else:
        kind, subject = "invocation", current.node_run_id
    return uuid5(
        _NAMESPACE,
        ":".join(
            str(part)
            for part in (
                current.organization_id,
                current.workflow_id,
                current.node_instance_id,
                agent_id,
                version_id,
                current.auth.subject_id,
                current.auth.api_key_id,
                kind,
                subject,
            )
        ),
    )


async def for_agent_step(
    db: AsyncSession,
    current: DispatchContext,
    *,
    agent_id: UUID,
    version_id: UUID,
) -> AgentConversation:
    """Keep an agent's workspace and history across chat turns without duplicate chat replies."""
    if current.workflow_id is None:
        raise NotFoundError(message="Workflow not found")
    project_id = None
    if current.source_conversation_id is not None:
        source = await conversation_repo.get_conversation_by_id(db, current.source_conversation_id)
        if source is None or source.organization_id != current.organization_id:
            raise NotFoundError(message="Conversation not found")
        project_id = source.project_id
    opened = await conversation_repo.ensure_workflow_conversation(
        db,
        conversation_id=conversation_key(current, agent_id, version_id),
        organization_id=current.organization_id,
        workflow_id=current.workflow_id,
        source_conversation_id=current.source_conversation_id,
        project_id=project_id,
    )
    if opened is None:
        raise NotFoundError(message="Conversation not found")
    history = await ConversationService(db).model_history(opened.id, limit=API_HISTORY_MESSAGES)
    return AgentConversation(opened.id, history)
