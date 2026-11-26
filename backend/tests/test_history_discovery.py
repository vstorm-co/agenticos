"""A stored model history preserves discovery without preserving authority."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2 as httpx
import pytest
from pydantic import JsonValue, TypeAdapter
from pydantic_ai import Agent, Tool
from pydantic_ai.capabilities import ToolSearch
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    NativeToolSearchReturnPart,
    TextPart,
    ToolAvailabilityDeltaPart,
    ToolCallPart,
    ToolReturnPart,
    ToolSearchReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.usage import RunUsage
from pydantic_ai_harness.compaction import SlidingWindowCompaction
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.approval import ApprovalGate
from app.agents.deps import AgentDeps
from app.agents.ephemeral_media import dump_messages
from app.agents.voice import AnswerUnknownTools
from app.db.models.conversation import Conversation, Message
from app.repositories import conversation_repo, conversation_share_repo
from app.schemas.conversation import HistoryCheckpointFrontier
from app.services.conversation import ConversationService
from app.services.message_history import (
    ModelHistory,
    bounded_stored_history,
    without_standing_instructions,
)
from tests.history_fixtures import CHECKPOINT_PROVENANCE as _PROVENANCE

pytestmark = pytest.mark.anyio
_JSON = TypeAdapter(dict[str, JsonValue])


@dataclass
class StoredThread:
    conversation: Conversation
    service: ConversationService

    async def save(self, messages: Sequence[ModelMessage]) -> ModelHistory:
        await self.service.keep_summary(
            self.conversation.id,
            bounded_stored_history(dump_messages(without_standing_instructions(messages))),
            expected_revision=0,
            expected_frontier=HistoryCheckpointFrontier(
                summary_ordinal=self.conversation.summary_ordinal,
                message_ordinal=self.conversation.summary_ordinal or 0,
            ),
            provenance=_PROVENANCE,
        )
        return await self.service.model_history(self.conversation.id, limit=50)


@pytest.fixture
def thread(monkeypatch: pytest.MonkeyPatch) -> StoredThread:
    conversation = Conversation(id=uuid4(), organization_id=uuid4(), guardrail_revision=0)
    service = ConversationService(AsyncMock(spec=AsyncSession))
    monkeypatch.setattr(conversation_share_repo, "has_edit_share", AsyncMock(return_value=False))
    monkeypatch.setattr(
        conversation_repo, "has_shared_channel_history", AsyncMock(return_value=False)
    )

    async def save(
        _db: AsyncSession,
        *,
        db_conversation: Conversation,
        messages: dict[str, JsonValue],
        ordinal: int,
        expected_revision: int,
        expected_frontier: HistoryCheckpointFrontier,
        through_message: Message | None,
    ) -> bool:
        assert expected_revision == db_conversation.guardrail_revision
        db_conversation.summary_messages = messages
        db_conversation.summary_ordinal = ordinal
        return True

    monkeypatch.setattr(
        conversation_repo, "get_conversation_by_id", AsyncMock(return_value=conversation)
    )
    monkeypatch.setattr(conversation_repo, "last_ordinal", AsyncMock(return_value=2))
    monkeypatch.setattr(conversation_repo, "set_summary", save)
    monkeypatch.setattr(conversation_repo, "get_recent_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(conversation_repo, "get_messages_after", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        conversation_repo, "capability_loads_in_messages", AsyncMock(return_value=[])
    )
    return StoredThread(conversation, service)


def discover(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
    if any(
        isinstance(part, ToolSearchReturnPart) for message in messages for part in message.parts
    ):
        return ModelResponse(parts=[TextPart("I found lookup_record.")])
    return ModelResponse(parts=[ToolCallPart("search_tools", {"queries": ["lookup_record"]})])


def local_agent(
    model: FunctionModel, tools: Sequence[Tool[AgentDeps]], *, approval: bool = False
) -> Agent[AgentDeps, str]:
    return Agent(
        model,
        tools=tools,
        capabilities=[
            ToolSearch(strategy="keywords"),
            AnswerUnknownTools(structured=True),
            ApprovalGate(gate_every_tool=True) if approval else ApprovalGate(),
        ],
    )


@pytest.mark.parametrize("compact", [False, True])
async def test_local_discovery_and_tool_evidence_survive_two_stored_turns(
    thread: StoredThread,
    compact: bool,
) -> None:
    calls: list[str] = []

    def lookup_record() -> str:
        """Look up the record."""
        calls.append("read")
        return "SOURCE_EVIDENCE_42"

    tools = [Tool[AgentDeps](lookup_record, defer_loading=True)]
    first = await local_agent(FunctionModel(discover), tools).run("Find the tool", deps=AgentDeps())
    history = await thread.save(
        await compacted(first.all_messages()) if compact else first.all_messages()
    )
    assert calls == []

    requests = 0

    def use(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        assert "lookup_record" in {tool.name for tool in info.function_tools}
        return ModelResponse(
            parts=[ToolCallPart("lookup_record", {})] if requests == 1 else [TextPart("Done")]
        )

    second = await local_agent(FunctionModel(use), tools).run(
        "Use it", deps=AgentDeps(), message_history=history
    )
    assert calls == ["read"]
    history = await thread.save(second.all_messages())
    assert "SOURCE_EVIDENCE_42" in ModelMessagesTypeAdapter.dump_json(history).decode()
    assert any(
        isinstance(part, ToolSearchReturnPart | ToolAvailabilityDeltaPart)
        for message in history
        for part in message.parts
    )
    assert requests == 2  # Call, then answer; there was no rediscovery request.


@pytest.mark.security
@pytest.mark.parametrize("change", ["removed", "unavailable", "approval"])
async def test_remembered_discovery_does_not_bypass_current_access_or_approval(
    thread: StoredThread, change: str
) -> None:
    calls: list[str] = []

    def lookup_record() -> str:
        """Look up the record."""
        calls.append("read")
        return "record"

    available = True

    async def prepare(
        _ctx: RunContext[AgentDeps], definition: ToolDefinition
    ) -> ToolDefinition | None:
        return definition if available else None

    tools = [Tool[AgentDeps](lookup_record, defer_loading=True, prepare=prepare)]
    first = await local_agent(FunctionModel(discover), tools).run("Find it", deps=AgentDeps())
    history = await thread.save(first.all_messages())
    available = change != "unavailable"
    requests = 0

    def use(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        return ModelResponse(
            parts=[ToolCallPart("lookup_record", {})] if requests == 1 else [TextPart("Stopped")]
        )

    result = await local_agent(
        FunctionModel(use), [] if change == "removed" else tools, approval=change == "approval"
    ).run("Use it", deps=AgentDeps(), message_history=history)
    assert calls == []
    returned = [
        part
        for message in result.new_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert returned
    assert (
        "tool_unavailable" in str(returned[0].content)
        if change != "approval"
        else "was not performed" in str(returned[0].content)
    )


@pytest.mark.parametrize("use_system_prompt", [False, True])
async def test_discovery_uses_the_current_schema_and_instructions(
    thread: StoredThread, use_system_prompt: bool
) -> None:
    def lookup_record() -> str:
        """Old schema."""
        return "old"

    first = await Agent(
        FunctionModel(discover),
        system_prompt="OLD_INSTRUCTIONS" if use_system_prompt else (),
        instructions=None if use_system_prompt else "OLD_INSTRUCTIONS",
        tools=[Tool(lookup_record, defer_loading=True)],
        capabilities=[ToolSearch(strategy="keywords")],
    ).run("Find it")
    history = await thread.save(first.all_messages())
    assert "OLD_INSTRUCTIONS" not in ModelMessagesTypeAdapter.dump_json(history).decode()

    def current(record_id: str) -> str:
        """Current schema."""
        return record_id

    def inspect(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool = next(tool for tool in info.function_tools if tool.name == "lookup_record")
        assert tool.parameters_json_schema["required"] == ["record_id"]
        assert "CURRENT_INSTRUCTIONS" in (info.instructions or "")
        return ModelResponse(parts=[TextPart("Current")])

    await Agent(
        FunctionModel(inspect),
        instructions="CURRENT_INSTRUCTIONS",
        tools=[Tool(current, name="lookup_record", defer_loading=True)],
        capabilities=[ToolSearch(strategy="keywords")],
    ).run("Continue", message_history=history)


@pytest.mark.parametrize("compact", [False, True])
async def test_anthropic_native_discovery_is_preserved_on_the_next_request(
    thread: StoredThread,
    compact: bool,
) -> None:
    calls: list[str] = []
    requests: list[dict[str, JsonValue]] = []

    def lookup_record() -> str:
        """Look up the record."""
        calls.append("read")
        return "NATIVE_EVIDENCE_42"

    def transport(request: httpx.Request) -> httpx.Response:
        body = _JSON.validate_json(request.content)
        requests.append(body)
        if len(requests) == 1:
            content = [
                {
                    "type": "server_tool_use",
                    "id": "srvtoolu_search",
                    "name": "tool_search_tool_bm25",
                    "input": {"query": "lookup_record"},
                },
                {
                    "type": "tool_search_tool_result",
                    "tool_use_id": "srvtoolu_search",
                    "content": {
                        "type": "tool_search_tool_search_result",
                        "tool_references": [
                            {"type": "tool_reference", "tool_name": "lookup_record"}
                        ],
                    },
                },
                {"type": "text", "text": "I found lookup_record."},
            ]
        elif len(requests) == 2:
            wire = json.dumps(body["messages"])
            assert "tool_reference" in wire
            assert "tool_search_tool_result" in wire or "tool_addition" in wire
            content = [
                {"type": "tool_use", "id": "toolu_lookup", "name": "lookup_record", "input": {}}
            ]
        else:
            content = [{"type": "text", "text": "Done."}]
        return httpx.Response(
            200,
            json={
                "id": f"msg_{len(requests)}",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "content": content,
                "stop_reason": "tool_use" if len(requests) == 2 else "end_turn",
                "usage": {"input_tokens": 50, "output_tokens": 10},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        model = AnthropicModel(
            "claude-sonnet-5-5",
            provider=AnthropicProvider(api_key="offline-test", http_client=client),
        )

        def agent() -> Agent[None, str]:
            return Agent(
                model,
                model_settings={"max_tokens": 100},
                tools=[Tool(lookup_record, defer_loading=True)],
                capabilities=[ToolSearch(strategy="bm25")],
            )

        first = await agent().run("Find it")
        history = await thread.save(
            await compacted(first.all_messages()) if compact else first.all_messages()
        )
        assert compact or any(
            isinstance(part, NativeToolSearchReturnPart)
            for message in history
            for part in message.parts
        )
        second = await agent().run("Use it", message_history=history)
        history = await thread.save(second.all_messages())
    assert calls == ["read"]
    assert len(requests) == 3
    assert "NATIVE_EVIDENCE_42" in ModelMessagesTypeAdapter.dump_json(history).decode()


async def test_snapshot_frontier_is_the_saved_answer_not_a_newer_message(
    thread: StoredThread, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = Message(
        id=uuid4(),
        conversation_id=thread.conversation.id,
        role="assistant",
        content="Done",
        ordinal=7,
    )
    monkeypatch.setattr(conversation_repo, "get_fork_point", AsyncMock(return_value=answer))
    monkeypatch.setattr(conversation_repo, "last_ordinal", AsyncMock(return_value=99))
    await thread.service.keep_summary(
        thread.conversation.id,
        [],
        expected_revision=0,
        expected_frontier=HistoryCheckpointFrontier(summary_ordinal=None, message_ordinal=0),
        through_message_id=str(answer.id),
        provenance=_PROVENANCE,
    )
    assert thread.conversation.summary_ordinal == 7


async def compacted(messages: list[ModelMessage]) -> list[ModelMessage]:
    tail = [
        *messages,
        ModelRequest(parts=[UserPromptPart("Keep working")]),
        ModelResponse(parts=[TextPart("Ready")]),
    ]
    ctx = RunContext(deps=None, model=TestModel(), usage=RunUsage())
    return await SlidingWindowCompaction(
        max_messages=2, keep_messages=2, preserve_first_user_message=False
    ).compact(tail, ctx)


@pytest.mark.security
async def test_a_stored_skill_load_requires_fresh_approval_when_the_policy_changes(
    thread: StoredThread,
) -> None:
    from pydantic_ai.capabilities import AbstractCapability
    from pydantic_ai.models import ModelRequestContext

    from app.agents.capabilities.skills import Skills
    from app.db.models.skill import Skill

    skill = Skill(
        name="interview", description="Interview", content="Interview instructions", resources=[]
    )

    def load(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if any(isinstance(part, ToolReturnPart) for message in messages for part in message.parts):
            return ModelResponse(parts=[TextPart("Ready")])
        return ModelResponse(
            parts=[ToolCallPart("load_capability", {"id": "interview"}, tool_call_id="load")]
        )

    first = await Agent(FunctionModel(load), capabilities=[Skills([skill])]).run("Load interview")
    history = await thread.save(first.all_messages())
    active: list[frozenset[str]] = []

    class ObserveLoads(AbstractCapability[AgentDeps]):
        async def before_model_request(
            self, ctx: RunContext[AgentDeps], request_context: ModelRequestContext
        ) -> ModelRequestContext:
            active.append(ctx.active_capability_ids)
            return request_context

    def finish(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("Waiting for a new load")])

    await Agent(
        FunctionModel(finish),
        capabilities=[
            Skills([skill]),
            ApprovalGate(required_tool_names=frozenset({"load_capability"})),
            ObserveLoads(),
        ],
    ).run("Continue", deps=AgentDeps(), message_history=history)
    assert active and all("interview" not in ids for ids in active)


@pytest.mark.security
@pytest.mark.parametrize("missing", [True, False])
async def test_a_checkpoint_cannot_claim_a_message_from_another_conversation(
    thread: StoredThread, monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
    answer = Message(
        id=uuid4(), conversation_id=uuid4(), role="assistant", content="Other", ordinal=7
    )
    monkeypatch.setattr(
        conversation_repo, "get_fork_point", AsyncMock(return_value=None if missing else answer)
    )
    await thread.service.keep_summary(
        thread.conversation.id,
        [],
        expected_revision=0,
        expected_frontier=HistoryCheckpointFrontier(summary_ordinal=None, message_ordinal=0),
        through_message_id=str(answer.id),
        provenance=_PROVENANCE,
    )
    assert thread.conversation.summary_messages is None


async def test_legacy_checkpoint_does_not_restore_an_old_agents_standing_prompt(
    thread: StoredThread,
) -> None:
    from pydantic_ai.messages import SystemPromptPart

    thread.conversation.summary_messages = dump_messages(
        [
            ModelRequest(
                parts=[SystemPromptPart("OLD_AGENT_PROMPT"), UserPromptPart("Find the record")]
            ),
            ModelResponse(parts=[TextPart("Found it")]),
        ]
    )
    thread.conversation.summary_ordinal = 2
    history = await thread.service.model_history(thread.conversation.id, limit=50)
    assert "OLD_AGENT_PROMPT" not in ModelMessagesTypeAdapter.dump_json(history).decode()
    assert "Find the record" not in ModelMessagesTypeAdapter.dump_json(history).decode()


async def test_replaying_a_compact_checkpoint_restores_large_media_without_eviction(
    thread: StoredThread, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic_ai.messages import BinaryContent, SystemPromptPart

    from app.agents.capabilities.media import MediaOffload
    from app.agents.capabilities.media import _store as stores
    from app.agents.capabilities.media._capability import offloaded_history
    from app.services.file_storage import LocalFileStorage
    from app.services.message_history import (
        HISTORY_TRIMMED,
        MODEL_HISTORY_BYTES,
        bounded_stored_history,
        without_standing_instructions,
    )

    storage = LocalFileStorage(base_dir=tmp_path)
    monkeypatch.setattr(stores, "get_file_storage", lambda: storage)
    binary = b"pixels" * 500_000
    messages = [
        ModelRequest(
            parts=[
                SystemPromptPart("OLD_AGENT_PROMPT"),
                UserPromptPart(
                    ["Read this chart", BinaryContent(data=binary, media_type="image/png")]
                ),
            ]
        ),
        ModelResponse(parts=[ToolCallPart("read_evidence", {}, tool_call_id="evidence")]),
        ModelRequest(
            parts=[ToolReturnPart("read_evidence", "SOURCE_EVIDENCE_42", tool_call_id="evidence")]
        ),
        ModelResponse(parts=[TextPart("The chart and evidence agree.")]),
    ]
    offload: MediaOffload[object] = MediaOffload(
        organization_id=thread.conversation.organization_id,
        conversation_id=thread.conversation.id,
    )
    checkpoint = bounded_stored_history(
        await offloaded_history([offload], dump_messages(without_standing_instructions(messages)))
    )
    assert len(json.dumps(checkpoint).encode()) < MODEL_HISTORY_BYTES
    assert "media+sha256://" in json.dumps(checkpoint)
    await thread.service.keep_summary(
        thread.conversation.id,
        checkpoint,
        expected_revision=0,
        expected_frontier=HistoryCheckpointFrontier(summary_ordinal=None, message_ordinal=0),
        provenance=_PROVENANCE,
    )
    # Restoring is unconditional even when the next agent does not bind MediaOffload.
    for _ in range(2):
        history = await thread.service.model_history(thread.conversation.id, limit=50)
        assert len(history) == 4
        prompt = history[0].parts[0]
        assert isinstance(prompt, UserPromptPart) and isinstance(prompt.content, list)
        restored = prompt.content[1]
        assert isinstance(restored, BinaryContent) and restored.data == binary
        encoded = ModelMessagesTypeAdapter.dump_json(history).decode()
        assert "SOURCE_EVIDENCE_42" in encoded
        assert HISTORY_TRIMMED not in encoded and "OLD_AGENT_PROMPT" not in encoded
        assert len(json.dumps(thread.conversation.summary_messages).encode()) < MODEL_HISTORY_BYTES


async def test_legacy_checkpoint_instructions_cannot_evict_evidence_when_the_tail_is_added(
    thread: StoredThread,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from pydantic_ai.messages import (
        InstructionBaselinePart,
        InstructionDeltaPart,
        InstructionPart,
        SystemPromptPart,
    )

    from app.schemas.conversation import HistoryCheckpoint
    from app.services import message_history

    standing = "OLD_STANDING_INSTRUCTIONS " * 50
    raw = dump_messages(
        [
            ModelRequest(
                parts=[
                    SystemPromptPart(standing),
                    InstructionBaselinePart(instructions=[InstructionPart(standing)]),
                    InstructionDeltaPart(id=None, content=standing),
                    UserPromptPart("Earlier question"),
                ],
                instructions=standing,
            ),
            ModelResponse(parts=[ToolCallPart("lookup", {}, tool_call_id="kept-call")]),
            ModelRequest(
                parts=[ToolReturnPart("lookup", "KEPT_SOURCE_EVIDENCE", tool_call_id="kept-call")],
                instructions=standing,
            ),
            ModelResponse(parts=[TextPart("Earlier answer")]),
        ]
    )
    checkpoint = HistoryCheckpoint(version=1, provenance=_PROVENANCE, messages=raw).model_dump(
        mode="json"
    )
    budget = len(json.dumps(checkpoint, ensure_ascii=False).encode()) + 100
    monkeypatch.setattr(message_history, "MODEL_HISTORY_BYTES", budget)
    thread.conversation.summary_messages = checkpoint
    thread.conversation.summary_ordinal = 2
    cleaned_size = len(
        json.dumps(message_history.without_stored_standing_instructions(raw)).encode()
    )
    tail = Message(
        id=uuid4(),
        ordinal=3,
        role="user",
        content="A new question " + "x" * (budget - cleaned_size - 350),
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(conversation_repo, "get_messages_after", AsyncMock(return_value=[tail]))
    old_bounded = message_history.bounded_stored_history(
        [*raw, *dump_messages([ModelRequest(parts=[UserPromptPart(tail.content)])])]
    )
    assert "KEPT_SOURCE_EVIDENCE" not in json.dumps(old_bounded)
    history = await thread.service.model_history(thread.conversation.id, limit=50)
    encoded = ModelMessagesTypeAdapter.dump_json(history).decode()
    assert "KEPT_SOURCE_EVIDENCE" in encoded
    assert "kept-call" in encoded
    assert "A new question" in encoded
    assert "OLD_STANDING_INSTRUCTIONS" not in encoded
    assert message_history.HISTORY_TRIMMED not in encoded
    assert thread.conversation.summary_messages["messages"] == raw
