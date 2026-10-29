"""A file the input guardrail refuses never reaches a lasting workspace (#2559).

Against a real database because the workspace that outlives the turn is a row: a
`state` workspace scoped to the conversation is the `files` column of its
`agent_workspaces` row, flushed when the run closes. The defect wrote the
attachment into that document while the prompt was built, before the input edge
screened the prompt, so a turn that ended `guardrail_blocked` still left the file
for the next turn of the conversation to open.
"""

import uuid
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
from app.db.models.agent_run import RunStatus, RunSurface
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services import attachments as attachments_module
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService
from app.services.attachments import workspace_path
from app.services.file_storage import LocalFileStorage
from tests.integration._keys import provider_key

pytestmark = [pytest.mark.anyio, pytest.mark.security]

BLOCKED = "XYZZY"


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


async def _attached(
    db: AsyncSession, storage: LocalFileStorage, ctx: AuthContext, *, text: str
) -> ChatFile:
    assert ctx.user_id is not None
    path = await storage.save(str(ctx.user_id), "notes.txt", text.encode())
    chat_file = ChatFile(
        id=uuid.uuid4(),
        user_id=ctx.user_id,
        filename="notes.txt",
        mime_type="text/plain",
        size=len(text),
        storage_path=path,
        file_type="text",
        parsed_content=text,
    )
    db.add(chat_file)
    await db.flush()
    return chat_file


async def _stored_files(db: AsyncSession, conversation_id: uuid.UUID) -> dict[str, object]:
    """What the conversation's workspace holds once its turns have closed, by
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
def model_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[ModelMessage]]:
    """Every request that reached the model; a refused turn adds none."""
    calls: list[list[ModelMessage]] = []

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(messages)
        return ModelResponse(parts=[TextPart("noted")])

    monkeypatch.setattr(ModelRequestSpec, "build", lambda self: FunctionModel(respond))
    return calls


class TestARefusedAttachmentStaysOutOfTheConversationWorkspace:
    async def test_a_guardrail_blocked_turn_leaves_no_file_for_the_next_turn(
        self, db: AsyncSession, storage: LocalFileStorage, model_calls: list[list[ModelMessage]]
    ) -> None:
        """The issue's sequence: the turn carrying the refused file is blocked,
        and the conversation's workspace - the one the next turn opens - has no
        trace of it."""
        ctx = await _owner(db)
        agent = await _guarded_agent(db, ctx)
        chat = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id)
        db.add(chat)
        await db.flush()
        refused = await _attached(db, storage, ctx, text=f"line one\n{BLOCKED} payload")

        _, run = await AgentRunnerService(db).execute(
            ctx,
            agent.id,
            "summarise the attached notes",
            surface=RunSurface.WEB,
            conversation_id=chat.id,
            attachments=[refused],
        )

        assert run.status == RunStatus.GUARDRAIL_BLOCKED.value
        assert model_calls == [], "the edge refused before any request"
        stored = await _stored_files(db, chat.id)
        assert workspace_path(refused) not in stored
        assert not any(path.startswith("uploads/") for path in stored)

    async def test_a_clean_file_in_the_same_conversation_still_lands(
        self, db: AsyncSession, storage: LocalFileStorage, model_calls: list[list[ModelMessage]]
    ) -> None:
        """The control: screening first does not stop an allowed file being written."""
        ctx = await _owner(db)
        agent = await _guarded_agent(db, ctx)
        chat = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id)
        db.add(chat)
        await db.flush()
        allowed = await _attached(db, storage, ctx, text="line one\nnothing to see")

        _, run = await AgentRunnerService(db).execute(
            ctx,
            agent.id,
            "summarise the attached notes",
            surface=RunSurface.WEB,
            conversation_id=chat.id,
            attachments=[allowed],
        )

        assert run.status == RunStatus.COMPLETED.value
        assert len(model_calls) == 1
        assert workspace_path(allowed) in await _stored_files(db, chat.id)
