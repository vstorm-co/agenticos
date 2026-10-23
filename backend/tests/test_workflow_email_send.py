"""`email.send` around a stubbed provider: who gets a copy, and what a refusal leaves."""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.core.permissions import AuthContext
from app.services.email.providers.base import SendResult
from app.services.email.service import EmailKey, EmailService
from app.services.email.templates import render_email
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed
from app.workflows.nodes.email_send import _handler as node

pytestmark = pytest.mark.anyio


class _Provider:
    """Accepts every message but those to `refuse`, and keeps what it was handed."""

    def __init__(self, *, delivers: bool = True, refuse: frozenset[str] = frozenset()) -> None:
        self.delivers = delivers
        self.refuse = refuse
        self.sent: list[Any] = []

    async def send(self, message: Any) -> SendResult:
        self.sent.append(message)
        accepted = message.to[0] not in self.refuse
        return SendResult(provider_message_id="m", accepted=accepted, error=None)


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> _Provider:
    state = _Provider()

    @asynccontextmanager
    async def session():
        yield MagicMock()

    async def app_name() -> str:
        return "Acme Agents"

    monkeypatch.setattr(node, "get_worker_db_context", session)
    monkeypatch.setattr(
        node, "DeploymentSettingsService", lambda _db: SimpleNamespace(effective_app_name=app_name)
    )
    monkeypatch.setattr(node, "get_email_service", lambda: EmailService(provider=state))
    return state


def _dispatch() -> context.DispatchContext:
    org = uuid.uuid4()
    return context.DispatchContext(
        organization_id=org,
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=AuthContext(user_id=uuid.uuid4(), organization_id=org, role="owner"),
        resumed_agent_run_id=None,
    )


async def _run(config: Any, **fields: Any):
    with context.dispatching_as(_dispatch()):
        return await node.handle(config, node.EmailSendInput(**fields))


async def test_each_address_gets_its_own_copy_once(provider):
    result = await _run(
        node.EmailSendConfig(reply_to="sales@acme.com"),
        to=["ada@example.com", "bob@example.com", "ada@example.com"],
        subject="Your quote",
        body="Hi,\n\n<b>42</b> EUR.",
    )

    assert isinstance(result, Completed)
    assert result.output.sent_to == ("ada@example.com", "bob@example.com")
    assert result.output.delivered is True
    assert [message.to for message in provider.sent] == [["ada@example.com"], ["bob@example.com"]]
    message = provider.sent[0]
    assert message.subject == "Your quote"
    assert message.reply_to == "sales@acme.com"
    assert "Hi,\n\n<b>42</b> EUR." in message.text and "Acme Agents" in message.text
    # The body is the workflow's text, not markup: the html copy escapes it.
    assert "&lt;b&gt;42&lt;/b&gt;" in message.html


async def test_a_provider_that_only_logs_mail_is_not_reported_as_delivering(provider):
    provider.delivers = False

    result = await _run(None, to=["ada@example.com"], subject="s", body="b")

    assert isinstance(result, Completed) and result.output.delivered is False
    assert provider.sent[0].reply_to is None


async def test_a_refused_copy_fails_the_step_naming_what_was_already_sent(provider):
    provider.refuse = frozenset({"bob@example.com"})

    result = await _run(
        None, to=["ada@example.com", "bob@example.com", "cy@example.com"], subject="s", body="b"
    )

    assert isinstance(result, Failed) and result.error.code == "EMAIL_NOT_SENT"
    assert result.error.details == {"refused": "bob@example.com", "sent_to": ["ada@example.com"]}
    assert len(provider.sent) == 2


async def test_a_step_with_nothing_to_send_fails():
    with context.dispatching_as(_dispatch()):
        result = await node.handle(None, None)

    assert isinstance(result, Failed) and result.error.code == "EMAIL_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "fields",
    [
        {"to": [], "subject": "s", "body": "b"},
        {"to": [f"p{i}@example.com" for i in range(11)], "subject": "s", "body": "b"},
        {"to": ["not an address"], "subject": "s", "body": "b"},
        {"to": ["ada@example.com"], "subject": "", "body": "b"},
    ],
)
def test_an_input_outside_the_limits_is_refused(fields):
    with pytest.raises(ValidationError):
        node.EmailSendInput(**fields)


def test_the_template_carries_the_workflows_subject_and_text():
    subject, html, text = render_email(
        EmailKey.WORKFLOW_MESSAGE.value, {"subject": "Hello", "body": "Line", "app_name": "Acme"}
    )

    assert subject == "Hello"
    assert "Line" in html and "Sent by Acme" in html
    assert text.startswith("Line")
