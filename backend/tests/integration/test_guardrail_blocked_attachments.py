"""A file the input guardrail refuses never reaches a lasting workspace (#2559).

Against a real database because the workspace that outlives the turn is a row: a
`state` workspace scoped to the conversation is the `files` column of its
`agent_workspaces` row, flushed when the run closes. The defect wrote the
attachment into that document while the prompt was built, before the input edge
screened the prompt, so a turn that ended `guardrail_blocked` still left the file
for the next turn of the conversation to open.
"""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.run import AgentRun
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.guardrails import GuardrailBlocked
from app.agents.deps import AgentDeps
from app.agents.factory import AgentOutput
from app.agents.model_resolver import ModelRequestSpec
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import RunStatus, RunSurface
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import conversation_repo
from app.repositories import retention as retention_repo
from app.services import attachments as attachments_module
from app.services.agent_chat import ChatAgentRunner
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService
from app.services.attachments import workspace_path
from app.services.conversation import ConversationService
from app.services.file_storage import LocalFileStorage
from app.services.message_history import REFUSED_TURN
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


async def _guarded_agent_without_a_workspace(db: AsyncSession, ctx: AuthContext) -> Agent:
    """The case #2563 leaves open: no workspace, so the file is pasted whole."""
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
            CapabilityBindingSpec(id="guardrails", config={"blocked_keywords_in": BLOCKED}),
        ],
    )
    registry = AgentRegistryService(db)
    agent = await registry.create(ctx, spec)
    await registry.publish(ctx, agent.id)
    return agent


class TestARefusedTurnIsNotReplayedToTheModel:
    async def test_the_next_turn_does_not_carry_the_refused_file_or_words(
        self, db: AsyncSession, storage: LocalFileStorage, model_calls: list[list[ModelMessage]]
    ) -> None:
        """#2578's reproduction: a blocked turn, then a harmless follow-up whose
        history is read back from the transcript. The input edge passes the new
        prompt, and the model must still see none of what it refused."""
        ctx = await _owner(db)
        agent = await _guarded_agent_without_a_workspace(db, ctx)
        chat = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id)
        db.add(chat)
        await db.flush()
        refused = await _attached(db, storage, ctx, text=f"line one\n{BLOCKED} payload")
        runner = AgentRunnerService(db)

        _, first = await runner.execute(
            ctx,
            agent.id,
            f"summarise the attached notes, starting at {BLOCKED}",
            surface=RunSurface.WEB,
            conversation_id=chat.id,
            attachments=[refused],
        )
        assert first.status == RunStatus.GUARDRAIL_BLOCKED.value

        history = await ConversationService(db).model_history(chat.id, limit=50)
        _, second = await runner.execute(
            ctx,
            agent.id,
            "what did the file I attached say?",
            surface=RunSurface.WEB,
            conversation_id=chat.id,
            message_history=history,
        )

        assert second.status == RunStatus.COMPLETED.value
        [request] = model_calls
        sent = repr(request)
        assert BLOCKED not in sent
        assert REFUSED_TURN in sent
        # The person's own transcript still says what they asked; only the
        # briefing the model would have been replayed is gone.
        rows = await db.execute(
            select(Message)
            .where(Message.run_id == first.id, Message.role == "user")
            .execution_options(populate_existing=True)
        )
        asked = rows.scalars().one()
        assert asked.content == f"summarise the attached notes, starting at {BLOCKED}"
        assert asked.attachment_context is None

    async def test_the_refusal_outlives_the_run_that_recorded_it(
        self, db: AsyncSession, storage: LocalFileStorage, model_calls: list[list[ModelMessage]]
    ) -> None:
        """Codex review of #2628: retention deletes a `guardrail_blocked` run, and
        `messages.run_id` is `SET NULL`. A refusal read off the run went with it,
        and the next turn replayed the prompt the edge had stopped."""
        ctx = await _owner(db)
        agent = await _guarded_agent_without_a_workspace(db, ctx)
        chat = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id)
        db.add(chat)
        await db.flush()
        _, first = await AgentRunnerService(db).execute(
            ctx,
            agent.id,
            f"say {BLOCKED}",
            surface=RunSurface.WEB,
            conversation_id=chat.id,
        )
        assert first.status == RunStatus.GUARDRAIL_BLOCKED.value
        asked_id = (
            await db.execute(
                select(Message.id).where(Message.run_id == first.id, Message.role == "user")
            )
        ).scalar_one()

        deleted, _ = await retention_repo.delete_runs_keeping_their_spend(
            db,
            organization_id=ctx.organization_id,
            cutoff=datetime.now(UTC) + timedelta(days=1),
            limit=100,
        )

        assert deleted >= 1
        asked = (
            await db.execute(
                select(Message)
                .where(Message.id == asked_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        assert asked.run_id is None, "the run is gone and the row no longer names it"
        sent = repr(await ConversationService(db).model_history(chat.id, limit=50))
        assert BLOCKED not in sent
        assert REFUSED_TURN in sent


class TestTheRefusalIsWrittenOnTheMessage:
    async def test_a_row_written_for_a_refused_run_is_marked_and_one_for_another_is_not(
        self, db: AsyncSession, storage: LocalFileStorage, model_calls: list[list[ModelMessage]]
    ) -> None:
        """Web chat writes the answer's row after the run has ended, in a session
        of its own: the mark is read off the run as the row is written."""
        ctx = await _owner(db)
        agent = await _guarded_agent_without_a_workspace(db, ctx)
        chat = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id)
        db.add(chat)
        await db.flush()
        runner = AgentRunnerService(db)
        _, blocked = await runner.execute(
            ctx, agent.id, f"say {BLOCKED}", surface=RunSurface.WEB, conversation_id=chat.id
        )
        _, allowed = await runner.execute(
            ctx, agent.id, "say hello", surface=RunSurface.WEB, conversation_id=chat.id
        )
        assert blocked.status == RunStatus.GUARDRAIL_BLOCKED.value
        assert allowed.status == RunStatus.COMPLETED.value

        late = await conversation_repo.create_message(
            db, conversation_id=chat.id, role="assistant", content="", run_id=blocked.id
        )
        fine = await conversation_repo.create_message(
            db, conversation_id=chat.id, role="assistant", content="hi", run_id=allowed.id
        )
        loose = await conversation_repo.create_message(
            db, conversation_id=chat.id, role="user", content="no run"
        )

        assert (late.guardrail_refused, fine.guardrail_refused, loose.guardrail_refused) == (
            True,
            False,
            False,
        )
        marked = dict(
            (
                await db.execute(
                    select(Message.run_id, Message.guardrail_refused)
                    .where(Message.role == "user", Message.run_id.is_not(None))
                    .where(Message.conversation_id == chat.id)
                )
            ).all()
        )
        assert marked == {blocked.id: True, allowed.id: False}

        # A link reads the run as `create_message` does, and never clears a mark.
        await conversation_repo.link_message_to_run(
            db, message_id=loose.id, run_id=blocked.id, conversation_id=chat.id
        )
        await conversation_repo.link_message_to_run(
            db, message_id=late.id, run_id=allowed.id, conversation_id=chat.id
        )
        relinked = dict(
            (
                await db.execute(
                    select(Message.id, Message.guardrail_refused).where(
                        Message.id.in_([loose.id, late.id])
                    )
                )
            ).all()
        )
        assert relinked == {loose.id: True, late.id: True}


class TestTheMarkIsBackfilledFromTheRuns:
    async def test_only_the_rows_of_a_refused_run_are_marked(
        self, db: AsyncSession, storage: LocalFileStorage, model_calls: list[list[ModelMessage]]
    ) -> None:
        """0249: rows written before the column read their refusal off the run
        once, while the run is still there to say so."""
        ctx = await _owner(db)
        agent = await _guarded_agent_without_a_workspace(db, ctx)
        chat = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id)
        db.add(chat)
        await db.flush()
        runner = AgentRunnerService(db)
        _, blocked = await runner.execute(
            ctx, agent.id, f"say {BLOCKED}", surface=RunSurface.WEB, conversation_id=chat.id
        )
        _, allowed = await runner.execute(
            ctx, agent.id, "say hello", surface=RunSurface.WEB, conversation_id=chat.id
        )
        # As a row from before the column reads: unmarked whatever its run did.
        await db.execute(
            update(Message)
            .where(Message.conversation_id == chat.id)
            .values(guardrail_refused=False)
        )

        await db.execute(text(_migration("0249_message_guardrail_refused").MARK_REFUSED))

        marked = {
            (run_id, role): refused
            for run_id, role, refused in (
                await db.execute(
                    select(Message.run_id, Message.role, Message.guardrail_refused).where(
                        Message.conversation_id == chat.id
                    )
                )
            ).all()
        }
        assert marked[(blocked.id, "user")] is True
        assert marked[(allowed.id, "user")] is False
        assert marked[(allowed.id, "assistant")] is False


def _migration(name: str = "0248_drop_refused_turn_summaries") -> ModuleType:
    path = Path(__file__).parents[2] / f"alembic/versions/{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestASummaryTakenBeforeTheFixIsDropped:
    async def test_only_a_summary_reaching_past_a_refused_prompt_is_cleared(
        self, db: AsyncSession, storage: LocalFileStorage, model_calls: list[list[ModelMessage]]
    ) -> None:
        """0248: a summary written before #2578 may quote a refused prompt word
        for word, and the stored summary is replayed as it is. One that ends
        before the refusal, or in a thread with none, says nothing it refused."""
        ctx = await _owner(db)
        agent = await _guarded_agent_without_a_workspace(db, ctx)
        runner = AgentRunnerService(db)
        chats: dict[str, Conversation] = {}
        for key in ("past_the_refusal", "before_the_refusal", "nothing_refused"):
            chats[key] = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id)
            db.add(chats[key])
        await db.flush()
        ordinals: dict[str, int] = {}
        for key in ("past_the_refusal", "before_the_refusal"):
            _, run = await runner.execute(
                ctx,
                agent.id,
                f"say {BLOCKED}",
                surface=RunSurface.WEB,
                conversation_id=chats[key].id,
            )
            assert run.status == RunStatus.GUARDRAIL_BLOCKED.value
            ordinals[key] = (
                await db.execute(select(Message.ordinal).where(Message.run_id == run.id))
            ).scalar_one()
        summary = [{"kind": "request", "parts": []}]
        for key, ordinal in (
            ("past_the_refusal", ordinals["past_the_refusal"]),
            ("before_the_refusal", ordinals["before_the_refusal"] - 1),
            ("nothing_refused", 5),
        ):
            chats[key].summary_messages = summary
            chats[key].summary_ordinal = ordinal
        await db.flush()

        await db.execute(text(_migration().DROP_SUMMARIES))

        kept = {
            key: (
                await db.execute(
                    select(Conversation.summary_ordinal).where(Conversation.id == chat.id)
                )
            ).scalar_one()
            for key, chat in chats.items()
        }
        assert kept == {
            "past_the_refusal": None,
            "before_the_refusal": ordinals["before_the_refusal"] - 1,
            "nothing_refused": 5,
        }


class TestAWebChatTurnTheEdgeRefusedKeepsNoBriefing:
    async def test_the_briefing_written_before_the_edge_is_taken_back(
        self, db: AsyncSession, storage: LocalFileStorage, model_calls: list[list[ModelMessage]]
    ) -> None:
        """Web chat writes what the file added onto the prompt's row before the
        input edge has read it (#2578). A refused turn must not leave it there:
        every later turn replays the row, and the edge reads only the new one."""
        ctx = await _owner(db)
        agent = await _guarded_agent_without_a_workspace(db, ctx)
        chat = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id)
        db.add(chat)
        await db.flush()
        refused = await _attached(db, storage, ctx, text=f"line one\n{BLOCKED} payload")
        prompt = await conversation_repo.create_message(
            db, conversation_id=chat.id, role="user", content="summarise the attached notes"
        )
        user = await db.get(User, ctx.user_id)
        assert user is not None

        async def stream(agent_run: AgentRun[AgentDeps, AgentOutput]) -> None:
            async for _ in agent_run:
                pass

        with pytest.raises(GuardrailBlocked):
            await ChatAgentRunner(db).run(
                user=user,
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                user_input="summarise the attached notes",
                message_history=[],
                conversation_id=chat.id,
                prompt_message_id=prompt.id,
                attachments=[refused],
                ask_user=AsyncMock(return_value=[]),
                stream=stream,
            )

        assert model_calls == []
        row = (
            await db.execute(
                select(Message)
                .where(Message.id == prompt.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        assert row.content == "summarise the attached notes"
        assert row.attachment_context is None
        # Marked in the transaction that ends the run: the row outlives it.
        assert row.guardrail_refused is True


@pytest.mark.parametrize("invalidated", [False, True])
@pytest.mark.parametrize("versioned", [False, True])
@pytest.mark.parametrize("external_source", [False, True])
async def test_a_parked_question_cannot_replay_history_refused_while_it_waited(
    db, model_calls, invalidated, versioned, external_source
):
    from pydantic_ai.messages import (
        ModelMessagesTypeAdapter,
        ModelRequest,
        ToolCallPart,
        UserPromptPart,
    )

    from app.services.agent_runner import PausedRunState
    from app.services.workflow_execution.agent_conversations import ChatSourceGuard
    from app.services.workflow_execution.context import ChatSource

    ctx = await _owner(db)
    agent = await _guarded_agent_without_a_workspace(db, ctx)
    chat = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id)
    db.add(chat)
    await db.flush()
    source_chat = chat
    if external_source:
        source_chat = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id)
        db.add(source_chat)
        await db.flush()
    source = await conversation_repo.create_message(
        db, conversation_id=source_chat.id, role="user", content=f"Remember {BLOCKED}"
    )
    history = await ConversationService(db).model_history(chat.id, limit=20)
    runner = AgentRunnerService(db)
    prepared = await runner.prepare(ctx, agent.id, surface=RunSurface.WEB, conversation_id=chat.id)
    question = {
        "questions": [
            {
                "header": "Tone",
                "question": "How formal?",
                "options": [{"label": "Formal"}, {"label": "Casual"}],
            }
        ]
    }
    paused = PausedRunState(
        messages=ModelMessagesTypeAdapter.dump_python(
            [
                *history,
                ModelRequest(parts=[UserPromptPart(content="Draft a reply")]),
                ModelResponse(
                    parts=[ToolCallPart("ask_user_question", question, tool_call_id="ask-1")]
                ),
            ],
            mode="json",
        ),
        tool_call_ids={},
        questions=["ask-1"],
        guardrail_revision=history.revision if versioned else None,
    )
    await runner.finish(prepared, status=RunStatus.AWAITING_ANSWER, paused_state=paused)
    await db.commit()
    assert ("guardrail_revision" in prepared.run.paused_state) is versioned
    if invalidated:
        await conversation_repo.mark_message_refused(
            db, message_id=source.id, conversation_id=source_chat.id
        )
        await db.commit()
    resumed = await runner.resume(
        ctx,
        prepared.run.id,
        answers={"ask-1": {"Tone": ["Formal"]}},
        on_run_open=ChatSourceGuard(db, ChatSource(source_chat.id, source.id)).check
        if external_source
        else None,
    )
    assert resumed.run.status == (
        RunStatus.GUARDRAIL_BLOCKED.value if invalidated else RunStatus.COMPLETED.value
    )
    assert len(model_calls) == (0 if invalidated else 1)
    assert resumed.run.paused_state is None


@pytest.mark.security
@pytest.mark.parametrize("surface", ["api", "chat"])
async def test_an_ordinary_turn_revalidates_history_loaded_before_a_refusal(
    db, model_calls, surface
):
    ctx = await _owner(db)
    agent = await _guarded_agent_without_a_workspace(db, ctx)
    chat = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id)
    db.add(chat)
    await db.flush()
    source = await conversation_repo.create_message(
        db, conversation_id=chat.id, role="user", content=f"Remember {BLOCKED}"
    )
    history = await ConversationService(db).model_history(chat.id, limit=20)
    await conversation_repo.mark_message_refused(db, message_id=source.id, conversation_id=chat.id)
    await db.commit()
    if surface == "api":
        _, run = await AgentRunnerService(db).execute(
            ctx,
            agent.id,
            "Continue",
            surface=RunSurface.API,
            conversation_id=chat.id,
            message_history=history,
        )
        assert run.status == RunStatus.GUARDRAIL_BLOCKED.value
    else:
        user = await db.get(User, ctx.user_id)
        assert user is not None
        with pytest.raises(GuardrailBlocked):
            await ChatAgentRunner(db).run(
                user=user,
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                user_input="Continue",
                message_history=history,
                conversation_id=chat.id,
                ask_user=AsyncMock(return_value=[]),
                stream=AsyncMock(),
            )
    assert model_calls == []


@pytest.mark.security
@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize("workflow_source", [False, True])
async def test_a_refusal_committed_during_a_tool_stops_the_next_provider_request(
    db, monkeypatch, streamed, workflow_source
):
    from pydantic_ai import Agent as PydanticAgent
    from pydantic_ai.messages import ToolCallPart
    from pydantic_ai.models.function import DeltaToolCall

    from app.db.session import get_db_context
    from app.services.workflow_execution.agent_conversations import ChatSourceGuard
    from app.services.workflow_execution.context import ChatSource

    ctx = await _owner(db)
    agent = await _guarded_agent_without_a_workspace(db, ctx)
    chat = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id)
    db.add(chat)
    await db.flush()
    source = await conversation_repo.create_message(
        db, conversation_id=chat.id, role="user", content=f"Remember {BLOCKED}"
    )
    source_id, conversation_id = source.id, chat.id
    history = (
        [] if workflow_source else await ConversationService(db).model_history(chat.id, limit=20)
    )
    calls = 0

    async def response(messages, info):
        nonlocal calls
        calls += 1
        return ModelResponse(parts=[ToolCallPart("invalidate_context", {}, tool_call_id="mark-1")])

    async def stream_response(messages, info):
        nonlocal calls
        calls += 1
        yield {0: DeltaToolCall(name="invalidate_context", json_args="{}", tool_call_id="mark-1")}

    monkeypatch.setattr(
        ModelRequestSpec,
        "build",
        lambda self: FunctionModel(response, stream_function=stream_response),
    )
    runner = AgentRunnerService(db)
    prepared = await runner.prepare(
        ctx,
        agent.id,
        surface=RunSurface.WORKFLOW if workflow_source else RunSurface.API,
        conversation_id=None if workflow_source else chat.id,
    )

    @prepared.built.agent.tool_plain
    async def invalidate_context() -> str:
        async with get_db_context() as own:
            await conversation_repo.mark_message_refused(
                own, message_id=source_id, conversation_id=conversation_id
            )
        return "done"

    async def stream(run):
        async for node in run:
            if PydanticAgent.is_model_request_node(node) or PydanticAgent.is_call_tools_node(node):
                async with node.stream(run.ctx) as events:
                    async for _ in events:
                        pass

    source_guard = ChatSourceGuard(db, ChatSource(conversation_id, source_id))
    segment = await runner._run(
        prepared,
        user_prompt="Continue",
        said="Continue",
        message_history=history,
        deferred_tool_results=None,
        stream=stream if streamed else None,
        check_model_request=source_guard.check_request if workflow_source else None,
    )
    assert segment.run.status == RunStatus.GUARDRAIL_BLOCKED.value
    assert calls == 1
