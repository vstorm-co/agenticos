"""Exact thread matching refuses spoofed, late, automated and unrelated messages."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.reply_expectation import ReplyExpectation, ReplyExpectationInput
from app.services.portals.reply_metadata import ReplyMessage
from app.services.reply_expectation import match_reply

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


def expectation() -> ReplyExpectation:
    return ReplyExpectation(
        provider="google",
        connection_id=uuid4(),
        authorization_generation=uuid4(),
        thread_id="thread",
        expected_sender="alice@example.com",
        not_before=NOW - timedelta(hours=1),
        deadline=NOW + timedelta(hours=1),
        anchor_message_id="<original@example.com>",
    )


def message() -> ReplyMessage:
    return ReplyMessage(
        message_id="message",
        thread_id="thread",
        sender="alice@example.com",
        received_at=NOW,
        authenticated=True,
        in_reply_to="<original@example.com>",
    )


def test_verified_reply_wins_over_deadline_and_is_deterministic():
    exp = expectation()
    answer = match_reply(
        exp, (message().model_copy(update={"message_id": "z"}), message()), now=exp.deadline
    )
    assert answer is not None and answer.branch == "reply" and answer.message_id == "message"
    assert match_reply(exp, (), now=NOW) is None
    answer = match_reply(exp, (), now=exp.deadline)
    assert answer is not None and answer.branch == "deadline"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("thread_id", "other"),
        ("sender", "mallory@example.com"),
        ("authenticated", False),
        ("sent_or_draft", True),
        ("automatic", True),
        ("in_reply_to", "<wrong@example.com>"),
        ("received_at", NOW - timedelta(hours=1)),
        ("received_at", NOW + timedelta(hours=2)),
    ],
)
def test_other_messages_never_satisfy_the_expectation(field: str, value: object):
    exp = expectation()
    changed = message().model_copy(update={field: value})
    assert match_reply(exp, (changed,), now=NOW) is None
    answer = match_reply(exp, (changed,), now=exp.deadline)
    assert answer is not None and answer.branch == "deadline"
    assert answer.ignored_unverified == (1 if field == "authenticated" else 0)


def test_references_narrow_the_thread_without_authorizing_the_sender():
    exp = expectation()
    reply = message().model_copy(update={"in_reply_to": "", "references": (exp.anchor_message_id,)})
    assert match_reply(exp, (reply,), now=NOW) is not None
    assert match_reply(exp, (reply.model_copy(update={"authenticated": False}),), now=NOW) is None
    assert (
        match_reply(exp.model_copy(update={"anchor_message_id": None}), (message(),), now=NOW)
        is not None
    )


@pytest.mark.parametrize(
    "change",
    [
        {"deadline": NOW - timedelta(hours=2)},
        {"thread_id": "x\n"},
        {"anchor_message_id": "unbracketed"},
        {"not_before": NOW.replace(tzinfo=None)},
        {"expected_sender": "not an email"},
    ],
)
def test_invalid_expectations_are_rejected(change: dict[str, object]):
    values = expectation().model_dump(
        exclude={
            "provider",
            "connection_id",
            "authorization_generation",
            "paused",
            "mailbox",
            "kind",
        }
    )
    with pytest.raises(ValidationError):
        ReplyExpectationInput.model_validate({**values, **change})
