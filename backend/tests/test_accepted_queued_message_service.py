"""Behavior checks for frozen queued messages at service boundaries."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.schemas.accepted_queued_message import AcceptedQueuedMessageCreate
from app.schemas.conversation import ChatPageContext
from app.schemas.mention import MentionRef
from app.services import accepted_queued_message as queue_service
from app.services.accepted_queued_message import AcceptedQueuedMessageService
from app.services.mentions import ResolvedMentions

pytestmark = pytest.mark.anyio


def _payload(**changes: object) -> AcceptedQueuedMessageCreate:
    data: dict[str, object] = {
        "client_queue_id": uuid4(),
        "agent_id": uuid4(),
        "content": "Write a short summary",
    }
    data.update(changes)
    return AcceptedQueuedMessageCreate.model_validate(data)


def _receipt(
    data: AcceptedQueuedMessageCreate,
    *,
    conversation_id: UUID,
    state: str = "pending",
    message_id: UUID | None = None,
    quote_snapshot: dict[str, str] | None = None,
) -> SimpleNamespace:
    payload = data.model_dump(mode="json")
    if quote_snapshot is not None or data.reply_to_message_id is not None:
        payload["quote_snapshot"] = quote_snapshot
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        requester_id=uuid4(),
        conversation_id=conversation_id,
        client_queue_id=data.client_queue_id,
        agent_id=data.agent_id,
        payload=payload,
        payload_hash=queue_service._fingerprint(data.model_dump(mode="json")),
        state=state,
        message_id=message_id,
        steering_run_id=None,
        created_at=datetime(2026, 11, 26, tzinfo=UTC),
    )


def _task(ctx: AuthContext, receipt: SimpleNamespace, **changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "queue_receipt_id": receipt.id,
        "prompt": "Saved task prompt",
        "source_conversation_id": receipt.conversation_id,
        "conversation_id": uuid4(),
        "user_id": ctx.user_id,
        "organization_id": ctx.organization_id,
        "agent_id": receipt.agent_id,
        "local_target": None,
        "source_run_id": None,
        "tool_call_id": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch):
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    result = AcceptedQueuedMessageService(db)
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    conversation = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(result, "_current_personal_context", AsyncMock(return_value=ctx))
    monkeypatch.setattr(result, "_personal_source", AsyncMock(return_value=conversation))
    monkeypatch.setattr(queue_service, "hold_subject", AsyncMock())
    return result, ctx, conversation


@pytest.mark.security
async def test_personal_queue_rejects_anonymous_and_mismatched_contexts() -> None:
    organization_id = uuid4()
    anonymous = AuthContext.anonymous(organization_id)
    service = AcceptedQueuedMessageService(object())

    with pytest.raises(AuthorizationError, match="signed-in organization member"):
        await service._current_personal_context(anonymous)
    with pytest.raises(AuthorizationError, match="signed-in organization member"):
        await service._personal_source(anonymous, uuid4())


@pytest.mark.security
async def test_agent_must_belong_to_the_calling_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AcceptedQueuedMessageService(object())
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    other_org_agent = SimpleNamespace(organization_id=uuid4())
    registry = SimpleNamespace(
        get_runnable_spec=AsyncMock(return_value=(other_org_agent, object(), uuid4()))
    )
    monkeypatch.setattr(queue_service, "AgentRegistryService", lambda _db: registry)

    with pytest.raises(NotFoundError, match="Agent not found"):
        await service._validate_agent(ctx, uuid4())


@pytest.mark.security
async def test_mention_validation_refuses_a_missing_member_then_resolves_allowed_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AcceptedQueuedMessageService(object())
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    refs = [MentionRef(kind="agent", id="helper")]
    monkeypatch.setattr(queue_service.user_repo, "get_by_id", AsyncMock(return_value=None))

    with pytest.raises(NotFoundError, match="Member not found"):
        await service._validate_mentions(ctx, uuid4(), refs)

    user = SimpleNamespace(id=ctx.user_id)
    expected = ResolvedMentions(mentions=[], note="Use the helper agent")
    runner = SimpleNamespace(mentions=AsyncMock(return_value=expected))
    monkeypatch.setattr(queue_service.user_repo, "get_by_id", AsyncMock(return_value=user))
    monkeypatch.setattr("app.services.agent_chat.ChatAgentRunner", lambda _db: runner)

    resolved = await service._validate_mentions(ctx, uuid4(), refs)

    assert resolved is expected
    runner.mentions.assert_awaited_once()


async def test_mention_parts_keep_resolved_mentions_in_transcript_shape() -> None:
    mention = SimpleNamespace(kind="agent", id="helper", name="Helper")

    assert queue_service._mention_parts(None) is None
    assert queue_service._mention_parts(SimpleNamespace(mentions=[])) is None
    assert queue_service._mention_parts(SimpleNamespace(mentions=[mention])) == [
        {
            "type": "mention",
            "mention_kind": "agent",
            "mention_id": "helper",
            "text": "Helper",
        }
    ]


@pytest.mark.security
async def test_queued_files_and_quotes_must_still_be_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AcceptedQueuedMessageService(object())
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    file_id = uuid4()
    monkeypatch.setattr(queue_service.receipt_repo, "files_for_owner", AsyncMock(return_value=[]))
    with pytest.raises(NotFoundError, match="queued files are no longer available"):
        await service._validate_files(ctx, [file_id])

    monkeypatch.setattr(queue_service.receipt_repo, "quote_message", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError, match="Quoted message not found"):
        await service._quote_snapshot(uuid4(), _payload(reply_to_message_id=uuid4()))

    quoted_id = uuid4()
    message = SimpleNamespace(
        id=quoted_id,
        role="assistant",
        content="Visible answer",
        guardrail_refused=False,
    )
    monkeypatch.setattr(
        queue_service.receipt_repo, "quote_message", AsyncMock(return_value=message)
    )
    with pytest.raises(BadRequestError, match="no longer visible"):
        await service._quote_snapshot(
            uuid4(),
            _payload(reply_to_message_id=quoted_id, reply_to_excerpt="Not in the answer"),
        )


@pytest.mark.security
async def test_read_refuses_a_receipt_that_lost_its_quote_snapshot() -> None:
    data = _payload(reply_to_message_id=uuid4(), reply_to_excerpt="Earlier answer")
    receipt = _receipt(data, conversation_id=uuid4())

    with pytest.raises(AlreadyExistsError, match="quote snapshot is missing"):
        AcceptedQueuedMessageService(object())._read(receipt)


@pytest.mark.security
async def test_accept_detects_racing_key_and_file_reservations(
    monkeypatch: pytest.MonkeyPatch, service
) -> None:
    current, ctx, conversation = service
    data = _payload()
    monkeypatch.setattr(queue_service.receipt_repo, "for_client_key", AsyncMock(return_value=None))
    monkeypatch.setattr(queue_service.receipt_repo, "pending_count", AsyncMock(return_value=0))
    monkeypatch.setattr(
        current, "_validate_agent", AsyncMock(return_value=(object(), object(), uuid4()))
    )

    conflicting = _receipt(data, conversation_id=conversation.id)
    conflicting.payload_hash = "different-key-payload"
    monkeypatch.setattr(
        queue_service.receipt_repo, "add_if_absent", AsyncMock(return_value=conflicting)
    )
    with pytest.raises(AlreadyExistsError, match="different queued message"):
        await current.accept(ctx, conversation.id, data)

    raced = _receipt(data, conversation_id=conversation.id, state="sent")
    monkeypatch.setattr(queue_service.receipt_repo, "add_if_absent", AsyncMock(return_value=raced))
    monkeypatch.setattr(current, "_validate_files", AsyncMock())
    read = await current.accept(ctx, conversation.id, data)
    assert read.state == "sent"
    current._validate_files.assert_not_awaited()

    file_id = uuid4()
    with_file = _payload(file_ids=[file_id])
    reserved_receipt = _receipt(with_file, conversation_id=conversation.id)
    monkeypatch.setattr(
        queue_service.receipt_repo, "add_if_absent", AsyncMock(return_value=reserved_receipt)
    )
    monkeypatch.setattr(
        current, "_validate_files", AsyncMock(return_value=[SimpleNamespace(id=file_id)])
    )
    monkeypatch.setattr(queue_service.receipt_repo, "reserve_files", AsyncMock(return_value=set()))
    with pytest.raises(AlreadyExistsError, match="claimed by another message"):
        await current.accept(ctx, conversation.id, with_file)


@pytest.mark.security
async def test_owner_lookup_and_cancel_return_or_refuse_the_correct_receipt(
    monkeypatch: pytest.MonkeyPatch, service
) -> None:
    current, ctx, conversation = service
    receipt_id = uuid4()
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError, match="Queued message not found"):
        await current.get_for_owner(ctx, conversation.id, receipt_id)
    with pytest.raises(NotFoundError, match="Queued message not found"):
        await current.cancel(ctx, conversation.id, receipt_id)

    data = _payload()
    cancelled = _receipt(data, conversation_id=conversation.id, state="cancelled")
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=cancelled))
    read = await current.cancel(ctx, conversation.id, cancelled.id)
    assert read.state == "cancelled"

    claimed = _receipt(data, conversation_id=conversation.id, state="sent")
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=claimed))
    with pytest.raises(AlreadyExistsError, match="already been claimed"):
        await current.cancel(ctx, conversation.id, claimed.id)


@pytest.mark.security
async def test_locked_receipt_rejects_missing_or_edited_payload(
    monkeypatch: pytest.MonkeyPatch, service
) -> None:
    current, ctx, conversation = service
    data = _payload()
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError, match="Queued message not found"):
        await current._locked_receipt(ctx, conversation.id, uuid4(), data)

    receipt = _receipt(data, conversation_id=conversation.id)
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=receipt))
    edited = data.model_copy(update={"content": "Changed after accept"})
    with pytest.raises(AlreadyExistsError, match="payload changed"):
        await current._locked_receipt(ctx, conversation.id, receipt.id, edited)


@pytest.mark.security
async def test_send_refuses_missing_message_changed_quote_and_lost_file(
    monkeypatch: pytest.MonkeyPatch, service
) -> None:
    current, ctx, conversation = service
    data = _payload()
    sent = _receipt(data, conversation_id=conversation.id, state="sent", message_id=uuid4())
    monkeypatch.setattr(current, "_locked_receipt", AsyncMock(return_value=(conversation, sent)))
    monkeypatch.setattr(queue_service.receipt_repo, "message_by_id", AsyncMock(return_value=None))
    with pytest.raises(AlreadyExistsError, match="message no longer exists"):
        await current.claim_for_send(ctx, conversation.id, sent.id)

    quoted_id = uuid4()
    quoted_data = _payload(reply_to_message_id=quoted_id, reply_to_excerpt="Frozen quote")
    quote = {"message_id": str(quoted_id), "role": "assistant", "excerpt": "Frozen quote"}
    quoted = _receipt(quoted_data, conversation_id=conversation.id, quote_snapshot=quote)
    monkeypatch.setattr(current, "_locked_receipt", AsyncMock(return_value=(conversation, quoted)))
    monkeypatch.setattr(current, "_validate_agent", AsyncMock())
    monkeypatch.setattr(current, "_validate_mentions", AsyncMock(return_value=None))
    monkeypatch.setattr(current, "_validate_files", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        current,
        "_quote_snapshot",
        AsyncMock(return_value={**quote, "excerpt": "Changed quote"}),
    )
    with pytest.raises(AlreadyExistsError, match="quoted message changed"):
        await current.claim_for_send(ctx, conversation.id, quoted.id)

    file_id = uuid4()
    file_data = _payload(file_ids=[file_id])
    file_receipt = _receipt(file_data, conversation_id=conversation.id)
    monkeypatch.setattr(
        current, "_locked_receipt", AsyncMock(return_value=(conversation, file_receipt))
    )
    monkeypatch.setattr(current, "_quote_snapshot", AsyncMock(return_value=None))
    monkeypatch.setattr(
        current, "_validate_files", AsyncMock(return_value=[SimpleNamespace(id=file_id)])
    )
    monkeypatch.setattr(
        queue_service.receipt_repo, "attach_reserved_files", AsyncMock(return_value=set())
    )
    with pytest.raises(AlreadyExistsError, match="claimed by another message"):
        await current.claim_for_send(ctx, conversation.id, file_receipt.id)


@pytest.mark.security
async def test_steering_and_completion_refuse_missing_or_ineligible_receipts(
    monkeypatch: pytest.MonkeyPatch, service
) -> None:
    current, ctx, conversation = service
    run_id = uuid4()
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError, match="Queued message not found"):
        await current.claim_for_steer(
            ctx, conversation.id, uuid4(), run_id=run_id, active_agent_id=uuid4()
        )
    with pytest.raises(NotFoundError, match="Queued message not found"):
        await current.finish_steer(ctx, conversation.id, uuid4(), run_id=run_id)
    with pytest.raises(NotFoundError, match="Queued message not found"):
        await current.release_unconsumed_steer(ctx, conversation.id, uuid4(), run_id=run_id)

    unclaimed = _receipt(_payload(), conversation_id=conversation.id)
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=unclaimed))
    with pytest.raises(AlreadyExistsError, match="not claimed by this run"):
        await current.finish_steer(ctx, conversation.id, unclaimed.id, run_id=run_id)

    with_file = _payload(file_ids=[uuid4()])
    receipt = _receipt(with_file, conversation_id=conversation.id)
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=receipt))
    with pytest.raises(BadRequestError, match="plain text queued message"):
        await current.claim_for_steer(
            ctx,
            conversation.id,
            receipt.id,
            run_id=run_id,
            active_agent_id=receipt.agent_id,
        )

    pending = _receipt(_payload(), conversation_id=conversation.id)
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=pending))
    assert (
        await current.release_unconsumed_steer(ctx, conversation.id, pending.id, run_id=run_id)
        is True
    )


@pytest.mark.security
async def test_task_transfer_refuses_unavailable_inconsistent_or_full_queue(
    monkeypatch: pytest.MonkeyPatch, service
) -> None:
    current, ctx, conversation = service
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError, match="Queued message not found"):
        await current.run_as_task(ctx, conversation.id, uuid4())

    data = _payload()
    already_task = _receipt(data, conversation_id=conversation.id, state="task")
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=already_task))
    monkeypatch.setattr(
        queue_service.receipt_repo, "task_for_receipt", AsyncMock(return_value=None)
    )
    with pytest.raises(AlreadyExistsError, match="already claimed"):
        await current.run_as_task(ctx, conversation.id, already_task.id)

    inconsistent = _receipt(data, conversation_id=conversation.id)
    inconsistent.payload["agent_id"] = str(uuid4())
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=inconsistent))
    with pytest.raises(AlreadyExistsError, match="record is inconsistent"):
        await current.run_as_task(ctx, conversation.id, inconsistent.id)

    quoted_id = uuid4()
    quoted_data = _payload(reply_to_message_id=quoted_id, reply_to_excerpt="Frozen quote")
    quote = {"message_id": str(quoted_id), "role": "assistant", "excerpt": "Frozen quote"}
    quoted = _receipt(quoted_data, conversation_id=conversation.id, quote_snapshot=quote)
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=quoted))
    monkeypatch.setattr(
        current, "_validate_agent", AsyncMock(return_value=(object(), object(), uuid4()))
    )
    monkeypatch.setattr(current, "_validate_mentions", AsyncMock(return_value=None))
    monkeypatch.setattr(current, "_validate_files", AsyncMock(return_value=[]))
    monkeypatch.setattr(current, "_quote_snapshot", AsyncMock(return_value=None))
    with pytest.raises(AlreadyExistsError, match="quoted message changed"):
        await current.run_as_task(ctx, conversation.id, quoted.id)

    full_receipt = _receipt(data, conversation_id=conversation.id)
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=full_receipt))
    monkeypatch.setattr(current, "_quote_snapshot", AsyncMock(return_value=None))
    monkeypatch.setattr(queue_service.task_repo, "active_count", AsyncMock(return_value=4))
    with pytest.raises(AlreadyExistsError, match="Four tasks are already active"):
        await current.run_as_task(ctx, conversation.id, full_receipt.id)


@pytest.mark.security
async def test_task_transfer_refuses_a_file_that_lost_its_reservation(
    monkeypatch: pytest.MonkeyPatch, service
) -> None:
    current, ctx, conversation = service
    file_id = uuid4()
    data = _payload(file_ids=[file_id])
    receipt = _receipt(data, conversation_id=conversation.id)
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=receipt))
    monkeypatch.setattr(
        current, "_validate_agent", AsyncMock(return_value=(object(), object(), uuid4()))
    )
    monkeypatch.setattr(current, "_validate_mentions", AsyncMock(return_value=None))
    monkeypatch.setattr(
        current, "_validate_files", AsyncMock(return_value=[SimpleNamespace(id=file_id)])
    )
    monkeypatch.setattr(current, "_quote_snapshot", AsyncMock(return_value=None))
    monkeypatch.setattr(queue_service.task_repo, "active_count", AsyncMock(return_value=0))
    monkeypatch.setattr(
        queue_service.receipt_repo, "attach_reserved_files", AsyncMock(return_value=set())
    )

    with pytest.raises(AlreadyExistsError, match="claimed by another task"):
        await current.run_as_task(ctx, conversation.id, receipt.id)


async def test_task_transfer_carries_the_resolved_mention_note(
    monkeypatch: pytest.MonkeyPatch, service
) -> None:
    current, ctx, conversation = service
    data = _payload(mentions=[{"kind": "agent", "id": "helper"}])
    receipt = _receipt(data, conversation_id=conversation.id)
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=receipt))
    monkeypatch.setattr(
        current,
        "_validate_agent",
        AsyncMock(return_value=(SimpleNamespace(id=data.agent_id), object(), uuid4())),
    )
    monkeypatch.setattr(
        current,
        "_validate_mentions",
        AsyncMock(return_value=ResolvedMentions(mentions=[], note="Use the helper agent")),
    )
    monkeypatch.setattr(current, "_validate_files", AsyncMock(return_value=[]))
    monkeypatch.setattr(current, "_quote_snapshot", AsyncMock(return_value=None))
    monkeypatch.setattr(queue_service.task_repo, "active_count", AsyncMock(return_value=0))

    added_tasks = []

    async def add_task(_db: object, task: object) -> None:
        added_tasks.append(task)
        task.created_at = datetime(2026, 11, 26, tzinfo=UTC)
        task.run_id = None
        task.return_run_id = None
        task.outcome = None

    monkeypatch.setattr(queue_service.task_repo, "add", AsyncMock(side_effect=add_task))
    monkeypatch.setattr(queue_service.task_repo, "save", AsyncMock())
    monkeypatch.setattr(queue_service, "enqueue", AsyncMock(return_value=uuid4()))

    task_read = await current.run_as_task(ctx, conversation.id, receipt.id)
    stored_task = added_tasks[0]

    assert stored_task.prompt == "Write a short summary\n\nUse the helper agent"
    assert task_read.id == stored_task.id
    assert task_read.conversation_id == stored_task.conversation_id


@pytest.mark.security
async def test_task_worker_refuses_missing_receipts_seeds_quotes_and_attachments(
    monkeypatch: pytest.MonkeyPatch, service
) -> None:
    current, ctx, conversation = service
    no_receipt = _task(
        ctx,
        SimpleNamespace(id=None, conversation_id=conversation.id, agent_id=uuid4()),
        queue_receipt_id=None,
    )
    assert await current.task_input_for_worker(ctx, no_receipt) == (no_receipt.prompt, None, [])

    data = _payload()
    receipt = _receipt(data, conversation_id=conversation.id, state="task", message_id=uuid4())
    task = _task(ctx, receipt)
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError, match="receipt is no longer available"):
        await current.task_input_for_worker(ctx, task)

    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=receipt))
    task.local_target = {"device_id": str(uuid4())}
    with pytest.raises(AlreadyExistsError, match="no longer matches its task"):
        await current.task_input_for_worker(ctx, task)

    task.local_target = None
    monkeypatch.setattr(
        queue_service.receipt_repo, "task_seed_message", AsyncMock(return_value=None)
    )
    with pytest.raises(NotFoundError, match="message is no longer available"):
        await current.task_input_for_worker(ctx, task)

    quoted_id = uuid4()
    quoted_data = _payload(reply_to_message_id=quoted_id, reply_to_excerpt="Frozen quote")
    quote = {"message_id": str(quoted_id), "role": "assistant", "excerpt": "Frozen quote"}
    quoted = _receipt(
        quoted_data,
        conversation_id=conversation.id,
        state="task",
        message_id=uuid4(),
        quote_snapshot=quote,
    )
    quoted_task = _task(ctx, quoted)
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=quoted))
    monkeypatch.setattr(
        queue_service.receipt_repo,
        "task_seed_message",
        AsyncMock(return_value=SimpleNamespace(id=quoted.message_id)),
    )
    monkeypatch.setattr(
        current, "_validate_agent", AsyncMock(return_value=(object(), object(), uuid4()))
    )
    monkeypatch.setattr(current, "_quote_snapshot", AsyncMock(return_value=None))
    with pytest.raises(AlreadyExistsError, match="quoted message changed"):
        await current.task_input_for_worker(ctx, quoted_task)

    file_id = uuid4()
    file_data = _payload(file_ids=[file_id])
    file_receipt = _receipt(
        file_data, conversation_id=conversation.id, state="task", message_id=uuid4()
    )
    file_task = _task(ctx, file_receipt)
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=file_receipt))
    monkeypatch.setattr(
        queue_service.receipt_repo,
        "task_seed_message",
        AsyncMock(return_value=SimpleNamespace(id=file_receipt.message_id)),
    )
    monkeypatch.setattr(current, "_quote_snapshot", AsyncMock(return_value=None))
    monkeypatch.setattr(current, "_validate_mentions", AsyncMock(return_value=None))
    monkeypatch.setattr(queue_service.chat_file_repo, "for_message", AsyncMock(return_value=[]))
    with pytest.raises(NotFoundError, match="task files are no longer available"):
        await current.task_input_for_worker(ctx, file_task)

    reserved = SimpleNamespace(id=file_id, queue_receipt_id=uuid4())
    monkeypatch.setattr(
        queue_service.chat_file_repo, "for_message", AsyncMock(return_value=[reserved])
    )
    with pytest.raises(AlreadyExistsError, match="still reserved"):
        await current.task_input_for_worker(ctx, file_task)


@pytest.mark.security
async def test_task_worker_rebuilds_quote_and_mention_context_and_refuses_stale_page(
    monkeypatch: pytest.MonkeyPatch, service
) -> None:
    current, ctx, conversation = service
    quoted_id = uuid4()
    page_context = ChatPageContext(
        path="/reports/weekly",
        title="Weekly report",
        captured_at="2026-11-26T10:00:00Z",
    )
    data = _payload(
        reply_to_message_id=quoted_id,
        reply_to_excerpt="Earlier answer",
        mentions=[{"kind": "agent", "id": "helper"}],
    )
    quote = {"message_id": str(quoted_id), "role": "assistant", "excerpt": "Earlier answer"}
    receipt = _receipt(
        data,
        conversation_id=conversation.id,
        state="task",
        message_id=uuid4(),
        quote_snapshot=quote,
    )
    task = _task(ctx, receipt)
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=receipt))
    monkeypatch.setattr(
        queue_service.receipt_repo,
        "task_seed_message",
        AsyncMock(return_value=SimpleNamespace(id=receipt.message_id)),
    )
    monkeypatch.setattr(
        current, "_validate_agent", AsyncMock(return_value=(object(), object(), uuid4()))
    )
    monkeypatch.setattr(
        current,
        "_validate_mentions",
        AsyncMock(return_value=ResolvedMentions(mentions=[], note="Use the helper agent")),
    )
    monkeypatch.setattr(current, "_quote_snapshot", AsyncMock(return_value=quote))
    monkeypatch.setattr(queue_service.chat_file_repo, "for_message", AsyncMock(return_value=[]))

    prompt, seed_id, attachments = await current.task_input_for_worker(ctx, task)

    assert prompt == (
        "Write a short summary\n\nQuoted earlier assistant message:\n> Earlier answer"
        "\n\nUse the helper agent"
    )
    assert seed_id == receipt.message_id
    assert attachments == []

    page_data = _payload(page_context=page_context)
    page_receipt = _receipt(
        page_data, conversation_id=conversation.id, state="task", message_id=uuid4()
    )
    page_task = _task(ctx, page_receipt)
    monkeypatch.setattr(queue_service.receipt_repo, "get", AsyncMock(return_value=page_receipt))
    monkeypatch.setattr(
        queue_service.receipt_repo,
        "task_seed_message",
        AsyncMock(return_value=SimpleNamespace(id=page_receipt.message_id)),
    )
    monkeypatch.setattr(current, "_validate_mentions", AsyncMock(return_value=None))
    monkeypatch.setattr(current, "_quote_snapshot", AsyncMock(return_value=None))
    monkeypatch.setattr("app.services.agent_chat.requested_page_context", lambda _value: None)
    with pytest.raises(BadRequestError, match="page context is no longer valid"):
        await current.task_input_for_worker(ctx, page_task)


async def test_prompt_compatibility_helper_returns_rebuilt_text(
    monkeypatch: pytest.MonkeyPatch, service
) -> None:
    current, ctx, conversation = service
    task = SimpleNamespace()
    monkeypatch.setattr(
        current,
        "task_input_for_worker",
        AsyncMock(return_value=("Rebuilt task prompt", uuid4(), [])),
    )

    assert await current.prompt_for_task(ctx, task) == "Rebuilt task prompt"
