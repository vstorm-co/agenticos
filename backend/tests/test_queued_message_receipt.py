"""Schema and defensive-boundary checks for accepted queue receipts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.db.models.accepted_queued_message import AcceptedQueuedMessage
from app.repositories import queued_message_receipt as receipt_repo
from app.schemas.accepted_queued_message import AcceptedQueuedMessageCreate

pytestmark = pytest.mark.anyio


def _payload(**changes: object) -> dict[str, object]:
    data: dict[str, object] = {
        "client_queue_id": uuid4(),
        "agent_id": uuid4(),
        "content": "Continue the report",
    }
    data.update(changes)
    return data


@pytest.mark.security
async def test_queue_schema_refuses_empty_text_or_invalid_quote_and_attachment_keys() -> None:
    with pytest.raises(ValidationError, match="needs text or an attachment"):
        AcceptedQueuedMessageCreate.model_validate(_payload(content=" \t "))

    with pytest.raises(ValidationError, match="needs a source message"):
        AcceptedQueuedMessageCreate.model_validate(_payload(reply_to_excerpt="A quote"))

    file_id = uuid4()
    with pytest.raises(ValidationError, match="may only appear once"):
        AcceptedQueuedMessageCreate.model_validate(_payload(file_ids=[file_id, file_id]))


async def test_receipt_repr_exposes_identity_and_disposition() -> None:
    receipt = AcceptedQueuedMessage(id=uuid4(), state="pending")

    assert repr(receipt) == f"<AcceptedQueuedMessage(id={receipt.id}, state=pending)>"


async def test_receipt_insert_reports_when_the_conflicting_row_is_not_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = SimpleNamespace(execute=AsyncMock())
    receipt = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        requester_id=uuid4(),
        conversation_id=uuid4(),
        client_queue_id=uuid4(),
        agent_id=uuid4(),
        payload={},
        payload_hash="0" * 64,
        state="pending",
    )
    monkeypatch.setattr(receipt_repo, "for_client_key", AsyncMock(return_value=None))

    with pytest.raises(RuntimeError, match="not visible after insertion"):
        await receipt_repo.add_if_absent(db, receipt)

    db.execute.assert_awaited_once()


async def test_empty_file_reservations_and_attachments_skip_database_writes() -> None:
    db = SimpleNamespace(execute=AsyncMock())

    assert await receipt_repo.reserve_files(db, set(), user_id=uuid4(), receipt_id=uuid4()) == set()
    assert (
        await receipt_repo.attach_reserved_files(
            db, set(), user_id=uuid4(), receipt_id=uuid4(), message_id=uuid4()
        )
        == set()
    )
    db.execute.assert_not_awaited()
