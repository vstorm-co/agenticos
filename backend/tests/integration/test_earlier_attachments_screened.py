"""A file put back from an interrupted turn passes the agent's input edge first (#2481).

A turn whose input the guardrail would refuse does not always end
`guardrail_blocked`: the turn budget is checked before the edge reads anything,
and a run can fail before its first model request. Such a turn ends `failed`
or `budget_exceeded`, which are the endings a later turn puts files back from -
so without a screen, a later turn wrote into the conversation's workspace a
file the input policy would have turned away.

Against a real database because the workspace that outlives the turn is a row:
a `state` workspace scoped to the conversation is the `files` column of its
`agent_workspaces` row, written when the run closes.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.model_resolver import ModelRequestSpec
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services import attachments as attachments_module
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService
from app.services.attachments import workspace_path
from app.services.conversation import ConversationService
from app.services.file_storage import LocalFileStorage
from tests.integration._keys import provider_key

pytestmark = [pytest.mark.anyio, pytest.mark.security]

BLOCKED = "XYZZY"
BRIEFING = "stopped before it finished"


async def _owner(db: AsyncSession) -> AuthContext:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name="Guarded",
        slug=f"guarded-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(organization)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid.uuid4(),
            organization_id=organization.id,
            user_id=user.id,
            role=OrgRoleName.OWNER.value,
        )
    )
    await db.flush()
    return AuthContext(
        user_id=user.id, organization_id=organization.id, role=OrgRoleName.OWNER.value
    )


async def _guarded_agent(db: AsyncSession, ctx: AuthContext) -> Agent:
    """An agent with a conversation-scoped `state` workspace and an input edge."""
    profile = ModelProfile(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        label="Default",
        provider="openai",
        model="gpt-4.1",
        secret_id=await provider_key(db, ctx.organization_id),
    )
    db.add(profile)
    await db.flush()
    spec = AgentSpec(
        name="Clerk",
        model_profile_id=profile.id,
        capabilities=[
            CapabilityBindingSpec(
                id="sandbox", config={"backend": "state", "session_scope": "conversation"}
            ),
            CapabilityBindingSpec(id="guardrails", config={"blocked_keywords_in": BLOCKED}),
        ],
    )
    registry = AgentRegistryService(db)
    agent = await registry.create(ctx, spec)
    await registry.publish(ctx, agent.id)
    return agent


async def _failed_turn(
    db: AsyncSession, ctx: AuthContext, agent: Agent, chat: Conversation
) -> Message:
    """A turn of this agent that ended `failed` before its files reached the workspace."""
    started = datetime.now(UTC) - timedelta(hours=1)
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        user_id=ctx.user_id,
        conversation_id=chat.id,
        status=RunStatus.FAILED.value,
        created_at=started,
        ended_at=started + timedelta(seconds=5),
    )
    db.add(run)
    await db.flush()
    message = Message(
        id=uuid.uuid4(),
        conversation_id=chat.id,
        role="user",
        content="summarise these",
        author_user_id=ctx.user_id,
        run_id=run.id,
    )
    db.add(message)
    await db.flush()
    return message


async def _attached(
    db: AsyncSession,
    storage: LocalFileStorage,
    ctx: AuthContext,
    message: Message,
    *,
    filename: str,
    text: str,
) -> ChatFile:
    """An upload linked to the failed turn, the way the chat links one before the run."""
    assert ctx.user_id is not None
    path = await storage.save(str(ctx.user_id), filename, text.encode())
    chat_file = ChatFile(
        id=uuid.uuid4(),
        user_id=ctx.user_id,
        filename=filename,
        mime_type="text/plain",
        size=len(text),
        storage_path=path,
        file_type="text",
        parsed_content=text,
    )
    db.add(chat_file)
    await db.flush()
    await ConversationService(db).link_files_to_message(
        message.id, [str(chat_file.id)], user_id=ctx.user_id
    )
    return chat_file


async def _stored_files(db: AsyncSession, conversation_id: uuid.UUID) -> dict[str, object]:
    """What the conversation's workspace holds once the turn has closed, by
    workspace path - the document keys its files from the root, `/uploads/...`."""
    rows = await db.execute(
        select(AgentWorkspace)
        .where(AgentWorkspace.conversation_id == conversation_id)
        .execution_options(populate_existing=True)
    )
    workspace = rows.scalars().one_or_none()
    if workspace is None or workspace.files is None:
        return {}
    return {path.lstrip("/"): data for path, data in workspace.files.items()}


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalFileStorage:
    store = LocalFileStorage(base_dir=tmp_path)
    monkeypatch.setattr(attachments_module, "get_file_storage", lambda: store)
    return store


@pytest.fixture
def same_session(monkeypatch: pytest.MonkeyPatch, db: AsyncSession) -> None:
    """The restore's own session, pointed at the test's: its rows are not committed."""

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(attachments_module, "get_db_context", session)


@pytest.fixture
def model_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[ModelMessage]]:
    """Every request that reached the model."""
    calls: list[list[ModelMessage]] = []

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(messages)
        return ModelResponse(parts=[TextPart("noted")])

    monkeypatch.setattr(ModelRequestSpec, "build", lambda self: FunctionModel(respond))
    return calls


async def _next_turn(db: AsyncSession, ctx: AuthContext, agent: Agent, chat: Conversation):
    _, run = await AgentRunnerService(db).execute(
        ctx,
        agent.id,
        "and now?",
        surface=RunSurface.WEB,
        conversation_id=chat.id,
    )
    return run


class TestARestoredFilePassesTheInputEdge:
    async def test_a_refused_file_is_not_put_back_and_an_allowed_one_is(
        self,
        db: AsyncSession,
        storage: LocalFileStorage,
        same_session: None,
        model_calls: list[list[ModelMessage]],
    ) -> None:
        ctx = await _owner(db)
        agent = await _guarded_agent(db, ctx)
        chat = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id)
        db.add(chat)
        await db.flush()
        failed = await _failed_turn(db, ctx, agent, chat)
        refused = await _attached(
            db, storage, ctx, failed, filename="notes.txt", text=f"line one\n{BLOCKED} payload"
        )
        allowed = await _attached(
            db, storage, ctx, failed, filename="sales.txt", text="month,total\njan,10"
        )

        run = await _next_turn(db, ctx, agent, chat)

        assert run.status == RunStatus.COMPLETED.value
        stored = await _stored_files(db, chat.id)
        assert workspace_path(allowed) in stored
        assert workspace_path(refused) not in stored
        assert BLOCKED not in str(stored)
        # Still told to look: one file is back.
        assert BRIEFING in str(model_calls[0])

    async def test_a_thread_whose_only_file_is_refused_is_told_nothing(
        self,
        db: AsyncSession,
        storage: LocalFileStorage,
        same_session: None,
        model_calls: list[list[ModelMessage]],
    ) -> None:
        """No briefing names a file as coming back when none will."""
        ctx = await _owner(db)
        agent = await _guarded_agent(db, ctx)
        chat = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id)
        db.add(chat)
        await db.flush()
        failed = await _failed_turn(db, ctx, agent, chat)
        refused = await _attached(
            db, storage, ctx, failed, filename=f"{BLOCKED}.txt", text="nothing inside"
        )

        run = await _next_turn(db, ctx, agent, chat)

        assert run.status == RunStatus.COMPLETED.value
        assert workspace_path(refused) not in await _stored_files(db, chat.id)
        assert BRIEFING not in str(model_calls[0])
