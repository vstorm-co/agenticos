"""Private replay follows a resolved agent and recipient configuration."""

from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, UserPromptPart

from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec
from app.core.secret_kinds import ApiKeySecret
from app.db.models.conversation import Message
from app.repositories import conversation_repo
from app.schemas.conversation import HistoryCheckpointFrontier
from app.services.agent_runner import _history_provenance
from app.services.conversation import ConversationService
from tests.history_fixtures import CHECKPOINT_PROVENANCE
from tests.test_history_audience_privacy import hidden_exchange
from tests.test_history_discovery import StoredThread
from tests.test_history_discovery import thread as thread

pytestmark = pytest.mark.anyio
_AGENT = UUID("00000000-0000-0000-0000-000000000002")
_USER = UUID("00000000-0000-0000-0000-000000000003")
_PROFILE = UUID("00000000-0000-0000-0000-000000000004")
_SPEC = AgentSpec(name="Private reader", model_profile_id=_PROFILE)


def _model() -> ModelRequestSpec:
    return ModelRequestSpec(
        profile_id=_PROFILE,
        label="Reader",
        provider="openai",
        model="gpt-4.1",
        params={},
        credential=ResolvedCredential(
            provider="openai",
            secret=ApiKeySecret(api_key="PRIVATE_KEY"),
            base_url="https://private-gateway.example/v1",
            api="chat",
            region="eu",
        ),
        fallbacks=[],
    )


@pytest.mark.parametrize(
    "change",
    [
        "agent",
        "profile",
        "endpoint",
        "provider",
        "model",
        "api",
        "region",
        "fallback",
        "fallback-endpoint",
        "subject",
        "spec",
        "params",
        "credential",
        "credential-generation",
        "routing",
        "fallback-credential",
    ],
)
def test_each_recipient_and_agent_configuration_change_partitions_replay(change: str) -> None:
    model = _model()
    if change in {"fallback-endpoint", "fallback-credential"}:
        model = replace(model, fallbacks=[(replace(model.credential), "fallback")])
    before = _history_provenance(_AGENT, _SPEC, model, _USER)
    agent, spec, user = _AGENT, _SPEC, _USER
    if change == "agent":
        agent = uuid4()
    elif change == "profile":
        model = replace(model, profile_id=uuid4())
    elif change == "endpoint":
        model = replace(
            model, credential=replace(model.credential, base_url="https://new.example/v1")
        )
    elif change == "provider":
        model = replace(
            model, provider="anthropic", credential=replace(model.credential, provider="anthropic")
        )
    elif change == "model":
        model = replace(model, model="another-model")
    elif change == "api":
        model = replace(model, credential=replace(model.credential, api="responses"))
    elif change == "region":
        model = replace(model, credential=replace(model.credential, region="global"))
    elif change == "fallback":
        model = replace(model, fallbacks=[(replace(model.credential), "fallback")])
    elif change == "fallback-endpoint":
        model = replace(
            model,
            fallbacks=[
                (replace(model.credential, base_url="https://other.example/v1"), "fallback")
            ],
        )
    elif change == "credential-generation":
        model = replace(
            model, credential=replace(model.credential, authorization_generation=uuid4())
        )
    elif change == "routing":
        model = replace(
            model,
            credential=replace(
                model.credential, routing={"azure_endpoint": "https://new.azure.example"}
            ),
        )
    elif change == "fallback-credential":
        model = replace(
            model, fallbacks=[(replace(model.credential, credential_id=uuid4()), "fallback")]
        )
    elif change == "subject":
        user = uuid4()
    elif change == "spec":
        spec = spec.model_copy(update={"instructions": "A different draft's instructions"})
    elif change == "params":
        model = replace(model, params={"provider": {"only": ["different-provider"]}})
    else:
        model = replace(model, secret_id=uuid4())
    after = _history_provenance(agent, spec, model, user)
    assert before != after
    assert "PRIVATE_KEY" not in after.model_dump_json()
    assert "gateway.example" not in after.model_dump_json()


def test_key_rotation_and_display_labels_do_not_change_the_recipient() -> None:
    model = _model()
    rotated = replace(
        model,
        label="New display name",
        credential=replace(model.credential, secret=ApiKeySecret(api_key="ROTATED_PRIVATE_KEY")),
    )
    assert _history_provenance(_AGENT, _SPEC, model, None) == _history_provenance(
        _AGENT, _SPEC, rotated, None
    )


@pytest.mark.security
@pytest.mark.parametrize("changed", [True, False, None])
async def test_only_a_matching_destination_replays_private_tool_evidence(
    thread: StoredThread,
    monkeypatch: pytest.MonkeyPatch,
    changed: bool | None,
) -> None:
    original = await thread.save(hidden_exchange())
    original.extend_public_context([ModelRequest(parts=[UserPromptPart("FRESH_THREAD_CONTEXT")])])
    monkeypatch.setattr(
        conversation_repo,
        "get_recent_messages",
        AsyncMock(
            return_value=[
                Message(id=uuid4(), ordinal=1, role="user", content="VISIBLE_QUESTION"),
                Message(id=uuid4(), ordinal=2, role="assistant", content="VISIBLE_ANSWER"),
            ]
        ),
    )
    target = (
        None
        if changed is None
        else (
            CHECKPOINT_PROVENANCE.model_copy(update={"configuration_digest": "b" * 64})
            if changed
            else CHECKPOINT_PROVENANCE
        )
    )
    replayed = await thread.service.history_for_provenance(original, target)
    assert replayed is not None
    text = ModelMessagesTypeAdapter.dump_json(replayed).decode()
    assert ("PRIVATE_EVENT_THERAPY" in text) is (changed is False)
    assert "FRESH_THREAD_CONTEXT" in text
    if changed is False:
        assert replayed is original
    else:
        assert "VISIBLE_QUESTION" in text and "VISIBLE_ANSWER" in text
        assert replayed.frontier == original.frontier


@pytest.mark.security
async def test_a_legacy_snapshot_without_recipient_proof_uses_only_visible_turns(
    thread: StoredThread,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread.conversation.summary_messages = ModelMessagesTypeAdapter.dump_python(
        hidden_exchange(), mode="json"
    )
    thread.conversation.summary_ordinal = 2
    monkeypatch.setattr(
        conversation_repo,
        "get_recent_messages",
        AsyncMock(
            return_value=[
                Message(id=uuid4(), ordinal=2, role="assistant", content="VISIBLE_ANSWER"),
            ]
        ),
    )
    history = await thread.service.model_history(thread.conversation.id, limit=50)
    text = ModelMessagesTypeAdapter.dump_json(history).decode()
    assert "PRIVATE_EVENT_THERAPY" not in text
    assert "VISIBLE_ANSWER" in text
    assert history.source is None


async def test_non_checkpoint_history_keeps_its_existing_contract() -> None:
    service = ConversationService(AsyncMock())
    history = hidden_exchange()
    assert await service.history_for_provenance(history, None) is history
    assert await service.history_for_provenance(None, None) is None


async def test_a_checkpoint_without_provenance_is_not_written() -> None:
    db = AsyncMock()
    await ConversationService(db).keep_summary(
        uuid4(),
        [],
        expected_revision=0,
        expected_frontier=HistoryCheckpointFrontier(summary_ordinal=None, message_ordinal=0),
    )
    db.execute.assert_not_awaited()


async def test_checkpoint_envelope_counts_against_the_storage_byte_ceiling(
    thread: StoredThread,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from pydantic_ai.messages import ModelRequest, UserPromptPart

    from app.agents.ephemeral_media import dump_messages
    from app.services import message_history

    monkeypatch.setattr(message_history, "MODEL_HISTORY_BYTES", 1000)
    messages = dump_messages([ModelRequest(parts=[UserPromptPart("x" * 650)])])
    await thread.service.keep_summary(
        thread.conversation.id,
        messages,
        expected_revision=0,
        expected_frontier=HistoryCheckpointFrontier(summary_ordinal=None, message_ordinal=0),
        provenance=CHECKPOINT_PROVENANCE,
    )
    stored = thread.conversation.summary_messages
    assert isinstance(stored, dict)
    assert len(json.dumps(stored, ensure_ascii=False).encode()) <= 1000
    assert "x" * 650 not in str(stored)


@pytest.mark.security
async def test_a_legacy_parked_private_history_is_refused_before_any_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.exceptions import BadRequestError
    from app.services import agent_runner
    from tests.test_agent_runner import _ctx, _db, _parked_run

    ctx = _ctx()
    service = agent_runner.AgentRunnerService(_db())
    run = _parked_run(organization_id=ctx.organization_id, user_id=ctx.user_id)
    run.paused_state = {
        "messages": ModelMessagesTypeAdapter.dump_python(hidden_exchange(), mode="json"),
        "tool_call_ids": {},
    }
    monkeypatch.setattr(
        agent_runner.agent_run_repo, "claim_parked_run", AsyncMock(return_value=run)
    )
    assemble = AsyncMock()
    monkeypatch.setattr(service, "_assemble", assemble)
    with pytest.raises(BadRequestError) as refused:
        await service.resume(ctx, run.id)
    assert refused.value.details == {
        "run_id": str(run.id),
        "code": "HISTORY_DESTINATION_UNVERIFIED",
    }
    assemble.assert_not_awaited()


@pytest.mark.parametrize("change", ["endpoint", "generation", "prefix", "account", "removed"])
def test_live_mcp_connections_partition_checkpoint_provenance(change: str) -> None:
    from app.agents.mcp import McpSourceIdentity
    from app.services.agent_runner import _bind_mcp_provenance

    identifier = uuid4()
    identity = McpSourceIdentity(
        endpoint_hash="a" * 64, authorization_generation=uuid4(), tool_prefix="records"
    )
    sources = {identifier: identity}
    model = _history_provenance(_AGENT, _SPEC, _model(), _USER)
    before = _bind_mcp_provenance(model, sources)
    if change == "endpoint":
        sources[identifier] = replace(identity, endpoint_hash="b" * 64)
    elif change == "generation":
        sources[identifier] = replace(identity, authorization_generation=uuid4())
    elif change == "prefix":
        sources[identifier] = replace(identity, tool_prefix="other_records")
    elif change == "account":
        sources = {uuid4(): identity}
    else:
        sources = {}
    assert _bind_mcp_provenance(model, sources) != before
    assert _bind_mcp_provenance(None, sources) is None


def test_the_order_of_resolved_mcp_accounts_does_not_change_the_proof() -> None:
    from app.agents.mcp import McpSourceIdentity
    from app.services.agent_runner import _bind_mcp_provenance

    sources = {
        uuid4(): McpSourceIdentity(endpoint_hash=str(i) * 64, authorization_generation=uuid4())
        for i in (1, 2)
    }
    model = _history_provenance(_AGENT, _SPEC, _model(), _USER)
    assert _bind_mcp_provenance(model, sources) == _bind_mcp_provenance(
        model, dict(reversed(list(sources.items())))
    )
