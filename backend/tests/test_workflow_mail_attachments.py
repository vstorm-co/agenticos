"""The Gmail trigger step storing a message's attachments as files of its run."""

import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.core.permissions import AuthContext
from app.services import portals
from app.services.mcp_connection import McpConnectionService
from app.services.portals import AttachmentTooLarge, PortalUnreachable
from app.services.workflow_execution import context
from app.services.workflow_execution.exceptions import WorkflowFileQuotaError
from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed
from app.workflows.nodes import _mail as mail
from app.workflows.nodes.trigger_gmail._handler import handle as gmail
from app.workflows.nodes.trigger_outlook._handler import handle as outlook

pytestmark = pytest.mark.anyio

TOKEN = "ya29.fixture-mailbox-token-5521"
PDF = b"%PDF-1.4 fixture invoice bytes"
TEXT = b"plain fixture notes"


def _dispatch(run_input: dict[str, Any], triggered_by: str = "gmail") -> context.DispatchContext:
    org = uuid.uuid4()
    return context.DispatchContext(
        organization_id=org,
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=AuthContext(user_id=uuid.uuid4(), organization_id=org, role="owner"),
        resumed_agent_run_id=None,
        run_input=run_input,
        triggered_by=triggered_by,
    )


def _item(
    attachment_id: str,
    *,
    name: str = "invoice.pdf",
    content_type: str = "application/pdf",
    byte_size: int | None = None,
) -> dict[str, Any]:
    return {
        "attachment_id": attachment_id,
        "name": name,
        "content_type": content_type,
        "byte_size": byte_size,
    }


def _message(*items: dict[str, Any]) -> dict[str, Any]:
    return {"message_id": "m1", "subject": "Invoice", "attachments": list(items)}


class _Adapter:
    """What the mailbox answers per attachment id: bytes, or the exception to raise."""

    portal_key = "google"

    def __init__(self, answers: dict[str, bytes | Exception]) -> None:
        self.answers = answers
        self.asked: list[dict[str, Any]] = []

    async def attachment(self, **kwargs: Any) -> bytes:
        self.asked.append(kwargs)
        answer = self.answers[kwargs["attachment_id"]]
        if isinstance(answer, Exception):
            raise answer
        return answer


class _Store:
    """The run's file store, in memory, with the real batch compensation on top."""

    def __init__(self) -> None:
        self.saved: list[tuple[bytes, str, str | None]] = []
        self.refs: list[FileRef] = []
        self.discarded: list[uuid.UUID] = []
        self.quota_after: int | None = None
        self.token = AsyncMock(return_value=TOKEN)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _Store:
    s = _Store()

    async def save(data: bytes, *, content_type: str, filename: str | None) -> FileRef:
        if s.quota_after is not None and len(s.saved) >= s.quota_after:
            raise WorkflowFileQuotaError(scope="run", limit=1, stored=1, requested=len(data))
        s.saved.append((data, content_type, filename))
        ref = FileRef(file_id=uuid.uuid4(), content_type=content_type, byte_size=len(data))
        s.refs.append(ref)
        return ref

    @asynccontextmanager
    async def session():
        yield object()

    async def delete_saved_batch(db: object, *, file_ids: list[uuid.UUID], **_: Any) -> list[str]:
        s.discarded.extend(file_ids)
        return []

    monkeypatch.setattr(files, "save", save)
    monkeypatch.setattr(files, "get_worker_db_context", session)
    monkeypatch.setattr(mail, "get_worker_db_context", session)
    monkeypatch.setattr(files, "hold_subject", AsyncMock())
    monkeypatch.setattr(files.workflow_file_repo, "delete_saved_batch", delete_saved_batch)
    monkeypatch.setattr(files, "delete_files_best_effort", AsyncMock())
    monkeypatch.setattr(McpConnectionService, "portal_read_token", s.token)
    return s


def _adapter(monkeypatch: pytest.MonkeyPatch, **answers: bytes | Exception) -> _Adapter:
    adapter = _Adapter(answers)
    monkeypatch.setattr(portals, "get_adapter", lambda key: adapter)
    return adapter


async def _run(run_input: dict[str, Any], triggered_by: str = "gmail"):
    with context.dispatching_as(_dispatch(run_input, triggered_by)):
        return await gmail(None, None)


def _reasons(result: Any) -> list[str | None]:
    assert isinstance(result, Completed)
    return [a.reason for a in result.output.attachments]


def _unreachable(status: int | None) -> PortalUnreachable:
    return PortalUnreachable(details={"portal_key": "google", "status": status})


async def test_two_attachments_are_stored_and_handed_on_as_files(store, monkeypatch):
    adapter = _adapter(monkeypatch, a1=PDF, a2=TEXT)
    result = await _run(
        _message(
            _item("a1"), _item("a2", name="notes.txt", content_type="application/octet-stream")
        )
    )
    assert isinstance(result, Completed)
    first, second = result.output.attachments
    assert first.stored and first.reason is None and first.file is not None
    assert first.file.byte_size == len(PDF) and first.file.content_type == "application/pdf"
    assert first.content_type == "application/pdf"
    # The stored type is what the bytes say; the sender's declared type stays on the entry.
    assert second.file is not None and second.file.content_type == "text/plain"
    assert second.content_type == "application/octet-stream"
    assert [(d, n) for d, _, n in store.saved] == [(PDF, "invoice.pdf"), (TEXT, "notes.txt")]
    assert store.token.await_count == 1
    assert adapter.asked[0]["access_token"] == TOKEN and adapter.asked[0]["message_id"] == "m1"
    assert adapter.asked[0]["mailbox"] is None
    assert adapter.asked[0]["max_bytes"] == settings.CHAT_MAX_UPLOAD_SIZE_MB * 1024 * 1024


async def test_an_executable_is_listed_by_name_and_never_fetched(store, monkeypatch):
    adapter = _adapter(monkeypatch)
    result = await _run(
        _message(_item("a1", name="setup.exe", content_type="application/x-msdownload"))
    )
    assert _reasons(result) == ["type_not_allowed"]
    assert result.output.attachments[0].name == "setup.exe"
    assert adapter.asked == [] and store.saved == []
    store.token.assert_not_awaited()


async def test_bytes_that_contradict_their_type_are_not_stored(store, monkeypatch):
    _adapter(monkeypatch, a1=b"this is not a png")
    result = await _run(_message(_item("a1", name="logo.png", content_type="image/png")))
    assert _reasons(result) == ["type_not_allowed"]
    assert store.saved == []


async def test_an_attachment_declared_over_the_limit_is_not_fetched(store, monkeypatch):
    monkeypatch.setattr(settings, "CHAT_MAX_UPLOAD_SIZE_MB", 1)
    adapter = _adapter(monkeypatch)
    result = await _run(_message(_item("a1", byte_size=1024 * 1024 + 1)))
    assert _reasons(result) == ["too_large"]
    assert adapter.asked == []


async def test_an_attachment_that_grows_past_the_limit_is_not_stored(store, monkeypatch):
    _adapter(monkeypatch, a1=AttachmentTooLarge(details={"portal_key": "google"}), a2=TEXT)
    result = await _run(
        _message(_item("a1", byte_size=10), _item("a2", name="n.txt", content_type="text/plain"))
    )
    assert _reasons(result) == ["too_large", None]
    assert len(store.saved) == 1


async def test_the_eleventh_attachment_is_too_many(store, monkeypatch):
    adapter = _adapter(monkeypatch, **{f"a{i}": TEXT for i in range(11)})
    items = [_item(f"a{i}", name=f"n{i}.txt", content_type="text/plain") for i in range(11)]
    result = await _run(_message(*items))
    assert _reasons(result) == [None] * 10 + ["too_many"]
    assert len(adapter.asked) == 10


async def test_the_message_total_stops_at_twenty_five_megabytes(store, monkeypatch):
    monkeypatch.setattr(mail, "MAX_STAGED_BYTES", len(TEXT) + 5)
    _adapter(monkeypatch, a1=TEXT, a2=TEXT, a3=b"tiny")
    items = [_item(f"a{i}", name=f"n{i}.txt", content_type="text/plain") for i in (1, 2, 3)]
    result = await _run(_message(*items))
    # The second would pass the total; the third is smaller and still fits.
    assert _reasons(result) == [None, "too_large", None]


async def test_the_total_is_twenty_five_mebibytes():
    assert mail.MAX_STAGED_BYTES == 25 * 1024 * 1024 and mail.MAX_STAGED_ATTACHMENTS == 10


async def test_a_full_quota_marks_the_attachment_and_staging_goes_on(store, monkeypatch):
    store.quota_after = 1
    _adapter(monkeypatch, a1=TEXT, a2=TEXT)
    items = [_item(f"a{i}", name=f"n{i}.txt", content_type="text/plain") for i in (1, 2)]
    result = await _run(_message(*items))
    assert _reasons(result) == [None, "quota"]


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_a_gone_attachment_is_unreadable_and_the_run_goes_on(store, monkeypatch, status):
    _adapter(monkeypatch, a1=_unreachable(status), a2=TEXT)
    result = await _run(_message(_item("a1"), _item("a2", name="n.txt", content_type="text/plain")))
    assert _reasons(result) == ["unreadable", None]


async def test_no_mailbox_grant_marks_every_attachment_unreadable(store, monkeypatch):
    store.token.return_value = None
    adapter = _adapter(monkeypatch)
    result = await _run(_message(_item("a1"), _item("a2")))
    assert _reasons(result) == ["unreadable", "unreadable"]
    assert adapter.asked == [] and store.token.await_count == 1


async def test_a_portal_without_a_reader_marks_the_attachment_unreadable(store, monkeypatch):
    monkeypatch.setattr(portals, "get_adapter", lambda key: None)
    result = await _run(_message(_item("a1")))
    assert _reasons(result) == ["unreadable"]


@pytest.mark.parametrize("status", [500, 429, None])
async def test_a_provider_outage_fails_the_step_for_a_retry_and_keeps_no_file(
    store, monkeypatch, status
):
    _adapter(monkeypatch, a1=TEXT, a2=_unreachable(status))
    result = await _run(
        _message(
            _item("a1", name="n.txt", content_type="text/plain"),
            _item("a2"),
        )
    )
    assert isinstance(result, Failed)
    assert result.error.code == "MAIL_ATTACHMENT_UNREACHABLE" and result.error.retryable
    assert result.error.details == {"portal_key": "google", "status": status}
    # The file stored before the outage is discarded with the attempt.
    assert store.discarded == [store.refs[0].file_id]


@pytest.mark.parametrize("triggered_by", ["test", "api"])
async def test_a_test_run_reads_nothing_from_the_mailbox(store, monkeypatch, triggered_by):
    adapter = _adapter(monkeypatch)
    result = await _run(_message(_item("a1"), _item("a2")), triggered_by)
    assert _reasons(result) == ["not_fetched", "not_fetched"]
    assert adapter.asked == [] and store.token.await_count == 0 and store.saved == []


async def test_a_message_without_attachments_asks_for_no_token(store, monkeypatch):
    adapter = _adapter(monkeypatch)
    result = await _run(_message())
    assert isinstance(result, Completed) and result.output.attachments == []
    store.token.assert_not_awaited()
    assert adapter.asked == []


async def test_no_token_or_byte_reaches_the_output_or_the_log(store, monkeypatch, caplog):
    _adapter(monkeypatch, a1=PDF, a2=_unreachable(404), a3=AttachmentTooLarge())
    with caplog.at_level(logging.DEBUG):
        result = await _run(_message(_item("a1"), _item("a2"), _item("a3")))
    assert isinstance(result, Completed)
    dumped = result.output.model_dump_json()
    assert TOKEN not in dumped and "fixture invoice bytes" not in dumped
    assert TOKEN not in caplog.text and "fixture invoice bytes" not in caplog.text


async def test_an_attachment_declared_past_what_is_left_of_the_total_is_not_fetched(
    store, monkeypatch
):
    monkeypatch.setattr(mail, "MAX_STAGED_BYTES", len(TEXT) + 5)
    adapter = _adapter(monkeypatch, a1=TEXT, a3=b"tiny")
    items = [
        _item("a1", name="n1.txt", content_type="text/plain"),
        _item("a2", name="n2.txt", content_type="text/plain", byte_size=len(TEXT)),
        _item("a3", name="n3.txt", content_type="text/plain", byte_size=4),
    ]
    result = await _run(_message(*items))
    assert _reasons(result) == [None, "too_large", None]
    assert [a["attachment_id"] for a in adapter.asked] == ["a1", "a3"]


async def test_an_outlook_run_stores_its_attachments_with_the_microsoft_grant(store, monkeypatch):
    adapter = _adapter(monkeypatch, a1=PDF)
    with context.dispatching_as(_dispatch(_message(_item("a1")), "outlook")):
        result = await outlook(None, None)
    assert _reasons(result) == [None]
    assert adapter.asked[0]["attachment_id"] == "a1"
    assert store.token.await_args.kwargs["portal_key"] == "microsoft"


async def test_an_outlook_trigger_reads_nothing_for_a_run_the_gmail_trigger_admitted(
    store, monkeypatch
):
    adapter = _adapter(monkeypatch)
    with context.dispatching_as(_dispatch(_message(_item("a1")), "gmail")):
        result = await outlook(None, None)
    assert _reasons(result) == ["not_fetched"]
    assert adapter.asked == []


async def test_an_outlook_outage_fails_the_step_for_a_retry(store, monkeypatch):
    _adapter(monkeypatch, a1=_unreachable(503))
    with context.dispatching_as(_dispatch(_message(_item("a1")), "outlook")):
        result = await outlook(None, None)
    assert isinstance(result, Failed) and result.error.code == "MAIL_ATTACHMENT_UNREACHABLE"


async def test_attachments_the_admission_left_unstored_are_not_read_again(store, monkeypatch):
    adapter = _adapter(monkeypatch)
    message = _message(
        {**_item("a1"), "reason": "not_fetched"}, {**_item("a2"), "reason": "not_fetched"}
    )

    result = await _run(message)

    assert _reasons(result) == ["not_fetched", "not_fetched"]
    assert adapter.asked == [] and store.token.await_count == 0 and store.saved == []
