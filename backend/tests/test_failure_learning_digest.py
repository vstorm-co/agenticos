"""The daily failure-ledger digest, and the choice it does not make for you.

The recipient is configuration, and while nobody has chosen one the job
must do nothing at all - no draft entries, no mail. When one is chosen,
each organization with a new pattern gets one digest, and only the new
patterns are drafted: a pattern already tracked, or one the one-open-entry
guard refuses, is skipped, not duplicated. One organization's failure must
not stop the rest of the estate from being digested.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AlreadyExistsError
from app.schemas.failure_learning import FailurePattern, FailurePatternList
from app.services.email.providers.base import SendResult
from app.worker.jobs import Tick
from app.worker.tasks.failure_learning_tasks import failure_ledger_digest

MODULE = "app.worker.tasks.failure_learning_tasks"

_TICK = Tick(scheduled_for=datetime.now(UTC))


def _pattern(**overrides: Any) -> FailurePattern:
    values: dict[str, Any] = {
        "agent_id": uuid.uuid4(),
        "agent_name": "Helper",
        "model": "anthropic:claude-sonnet-4-5",
        "status": "failed",
        "error_class": "ModelHTTPError:400",
        "pattern_key": "failed:ModelHTTPError:400",
        "count": 4,
        "first_seen": datetime(2026, 11, 3, tzinfo=UTC),
        "last_seen": datetime(2026, 11, 9, tzinfo=UTC),
        "sample_run_ids": [uuid.uuid4()],
        "already_tracked": False,
    }
    values.update(overrides)
    return FailurePattern(**values)


def _model_pattern(**overrides: Any) -> FailurePattern:
    values: dict[str, Any] = {
        "agent_id": None,
        "agent_name": None,
        "model": "anthropic:claude-sonnet-4-5",
    }
    values.update(overrides)
    return _pattern(**values)


@asynccontextmanager
async def _fake_db_context():
    yield MagicMock()


def _org(name="Example Org"):
    org = MagicMock()
    org.id = uuid.uuid4()
    org.name = name
    return org


def _service(patterns, *, create_side_effect=None):
    service = MagicMock()
    service.list_org_patterns = AsyncMock(
        return_value=FailurePatternList(items=patterns, total=len(patterns), notes=[])
    )
    service.create_ledger = AsyncMock(side_effect=create_side_effect)
    return service


def _mail(*, accepted=True):
    service = MagicMock()
    service.send = AsyncMock(return_value=SendResult(provider_message_id="m1", accepted=accepted))
    return service


@pytest.mark.anyio
async def test_no_recipient_means_logged_no_op(caplog):
    """Empty recipient: no mining, no drafts, no mail - the job is a no-op."""
    list_all = AsyncMock(return_value=[])
    with (
        patch(f"{MODULE}.settings", SimpleNamespace(FAILURE_LEARNING_DIGEST_RECIPIENT="")),
        patch(f"{MODULE}.get_db_context", _fake_db_context),
        patch(f"{MODULE}.organization_repo.list_all", new=list_all),
    ):
        counts = await failure_ledger_digest(_TICK)

    assert counts == {
        "recipient_configured": False,
        "organizations": 0,
        "entries_created": 0,
        "digests_sent": 0,
    }
    list_all.assert_not_awaited()
    assert "failure_ledger_digest_skipped_no_recipient_configured" in caplog.text


@pytest.mark.anyio
async def test_new_patterns_are_drafted_and_digested_once():
    """One digest per org with new patterns; tracked patterns are skipped."""
    org = _org()
    service = _service([_pattern(), _pattern(pattern_key="failed:Other", already_tracked=True)])
    mail = _mail()

    with (
        patch(
            f"{MODULE}.settings",
            SimpleNamespace(FAILURE_LEARNING_DIGEST_RECIPIENT="ops@example.test"),
        ),
        patch(f"{MODULE}.get_db_context", _fake_db_context),
        patch(f"{MODULE}.organization_repo.list_all", new=AsyncMock(return_value=[org])),
        patch(f"{MODULE}.FailureLearningService", return_value=service),
        patch(f"{MODULE}.get_email_service", return_value=mail),
    ):
        counts = await failure_ledger_digest(_TICK)

    assert counts["entries_created"] == 1
    assert counts["digests_sent"] == 1
    assert service.create_ledger.await_count == 1
    created = service.create_ledger.await_args.args[2]
    assert created.scope == "agent"
    assert created.pattern_key == "failed:ModelHTTPError:400"
    mail.send.assert_awaited_once()
    send_kwargs = mail.send.await_args.kwargs
    assert send_kwargs["to"] == "ops@example.test"
    assert send_kwargs["context"]["org_name"] == "Example Org"
    assert "ModelHTTPError:400" in send_kwargs["context"]["summary"]


@pytest.mark.anyio
async def test_nothing_new_means_silence_not_an_empty_digest():
    """An org with no untracked patterns gets no email at all."""
    service = _service([_pattern(already_tracked=True)])
    mail = _mail()

    with (
        patch(
            f"{MODULE}.settings",
            SimpleNamespace(FAILURE_LEARNING_DIGEST_RECIPIENT="ops@example.test"),
        ),
        patch(f"{MODULE}.get_db_context", _fake_db_context),
        patch(f"{MODULE}.organization_repo.list_all", new=AsyncMock(return_value=[_org()])),
        patch(f"{MODULE}.FailureLearningService", return_value=service),
        patch(f"{MODULE}.get_email_service", return_value=mail),
    ):
        counts = await failure_ledger_digest(_TICK)

    assert counts == {
        "recipient_configured": True,
        "organizations": 1,
        "entries_created": 0,
        "digests_sent": 0,
    }
    service.create_ledger.assert_not_awaited()
    mail.send.assert_not_awaited()


@pytest.mark.anyio
async def test_a_model_pattern_is_anchored_on_its_sample_run():
    """The entry stays model-scoped; the anchor only picks the ledger."""
    run = MagicMock()
    run.agent_id = uuid.uuid4()
    service = _service([_model_pattern()])
    mail = _mail()

    with (
        patch(
            f"{MODULE}.settings",
            SimpleNamespace(FAILURE_LEARNING_DIGEST_RECIPIENT="ops@example.test"),
        ),
        patch(f"{MODULE}.get_db_context", _fake_db_context),
        patch(f"{MODULE}.organization_repo.list_all", new=AsyncMock(return_value=[_org()])),
        patch(f"{MODULE}.FailureLearningService", return_value=service),
        patch(f"{MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=run)),
        patch(f"{MODULE}.get_email_service", return_value=mail),
    ):
        counts = await failure_ledger_digest(_TICK)

    assert counts["entries_created"] == 1
    anchor_id, created = service.create_ledger.await_args.args[1:3]
    assert anchor_id == run.agent_id
    assert created.scope == "model"
    assert created.model == "anthropic:claude-sonnet-4-5"


@pytest.mark.anyio
async def test_a_model_pattern_with_no_sample_run_is_skipped_not_guessed():
    """No run to anchor on means no entry: the pattern waits for tomorrow."""
    service = _service([_model_pattern(sample_run_ids=[])])
    mail = _mail()

    with (
        patch(
            f"{MODULE}.settings",
            SimpleNamespace(FAILURE_LEARNING_DIGEST_RECIPIENT="ops@example.test"),
        ),
        patch(f"{MODULE}.get_db_context", _fake_db_context),
        patch(f"{MODULE}.organization_repo.list_all", new=AsyncMock(return_value=[_org()])),
        patch(f"{MODULE}.FailureLearningService", return_value=service),
        patch(f"{MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=None)),
        patch(f"{MODULE}.get_email_service", return_value=mail),
    ):
        counts = await failure_ledger_digest(_TICK)

    assert counts["entries_created"] == 0
    assert counts["digests_sent"] == 0
    service.create_ledger.assert_not_awaited()
    mail.send.assert_not_awaited()


@pytest.mark.anyio
async def test_the_anchor_is_the_first_sample_run_that_still_exists():
    """A sample run deleted since mining must not stop the anchor search."""
    run = MagicMock()
    run.agent_id = uuid.uuid4()
    service = _service([_model_pattern(sample_run_ids=[uuid.uuid4(), uuid.uuid4()])])
    mail = _mail()

    with (
        patch(
            f"{MODULE}.settings",
            SimpleNamespace(FAILURE_LEARNING_DIGEST_RECIPIENT="ops@example.test"),
        ),
        patch(f"{MODULE}.get_db_context", _fake_db_context),
        patch(f"{MODULE}.organization_repo.list_all", new=AsyncMock(return_value=[_org()])),
        patch(f"{MODULE}.FailureLearningService", return_value=service),
        patch(f"{MODULE}.agent_run_repo.get_run", new=AsyncMock(side_effect=[None, run])),
        patch(f"{MODULE}.get_email_service", return_value=mail),
    ):
        counts = await failure_ledger_digest(_TICK)

    assert counts["entries_created"] == 1
    assert service.create_ledger.await_args.args[1] == run.agent_id


@pytest.mark.anyio
async def test_a_model_pattern_with_no_model_label_is_still_named():
    """A model-scoped pattern naming no model is digested as 'all models'."""
    run = MagicMock()
    run.agent_id = uuid.uuid4()
    service = _service([_model_pattern(model=None)])
    mail = _mail()

    with (
        patch(
            f"{MODULE}.settings",
            SimpleNamespace(FAILURE_LEARNING_DIGEST_RECIPIENT="ops@example.test"),
        ),
        patch(f"{MODULE}.get_db_context", _fake_db_context),
        patch(f"{MODULE}.organization_repo.list_all", new=AsyncMock(return_value=[_org()])),
        patch(f"{MODULE}.FailureLearningService", return_value=service),
        patch(f"{MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=run)),
        patch(f"{MODULE}.get_email_service", return_value=mail),
    ):
        counts = await failure_ledger_digest(_TICK)

    assert counts["entries_created"] == 1
    assert "all models" in mail.send.await_args.kwargs["context"]["summary"]


@pytest.mark.anyio
async def test_an_agent_pattern_with_no_name_is_still_named():
    """An agent the mining could not name is digested as 'unknown agent'."""
    service = _service([_pattern(agent_name=None)])
    mail = _mail()

    with (
        patch(
            f"{MODULE}.settings",
            SimpleNamespace(FAILURE_LEARNING_DIGEST_RECIPIENT="ops@example.test"),
        ),
        patch(f"{MODULE}.get_db_context", _fake_db_context),
        patch(f"{MODULE}.organization_repo.list_all", new=AsyncMock(return_value=[_org()])),
        patch(f"{MODULE}.FailureLearningService", return_value=service),
        patch(f"{MODULE}.get_email_service", return_value=mail),
    ):
        counts = await failure_ledger_digest(_TICK)

    assert counts["entries_created"] == 1
    assert "unknown agent" in mail.send.await_args.kwargs["context"]["summary"]


@pytest.mark.anyio
async def test_a_pattern_drafted_since_mining_is_not_duplicated():
    """The one-open-entry guard is the second opinion after already_tracked."""
    service = _service(
        [_pattern()],
        create_side_effect=AlreadyExistsError(
            message="An open ledger entry already covers this pattern",
            details={"pattern_key": "failed:ModelHTTPError:400"},
        ),
    )
    mail = _mail()

    with (
        patch(
            f"{MODULE}.settings",
            SimpleNamespace(FAILURE_LEARNING_DIGEST_RECIPIENT="ops@example.test"),
        ),
        patch(f"{MODULE}.get_db_context", _fake_db_context),
        patch(f"{MODULE}.organization_repo.list_all", new=AsyncMock(return_value=[_org()])),
        patch(f"{MODULE}.FailureLearningService", return_value=service),
        patch(f"{MODULE}.get_email_service", return_value=mail),
    ):
        counts = await failure_ledger_digest(_TICK)

    assert counts["entries_created"] == 0
    assert counts["digests_sent"] == 0
    mail.send.assert_not_awaited()


@pytest.mark.anyio
async def test_a_mail_provider_that_refuses_is_counted_not_crashed_on():
    """Accepted=False is a digest that did not go out, not an exception."""
    service = _service([_pattern()])
    mail = _mail(accepted=False)

    with (
        patch(
            f"{MODULE}.settings",
            SimpleNamespace(FAILURE_LEARNING_DIGEST_RECIPIENT="ops@example.test"),
        ),
        patch(f"{MODULE}.get_db_context", _fake_db_context),
        patch(f"{MODULE}.organization_repo.list_all", new=AsyncMock(return_value=[_org()])),
        patch(f"{MODULE}.FailureLearningService", return_value=service),
        patch(f"{MODULE}.get_email_service", return_value=mail),
    ):
        counts = await failure_ledger_digest(_TICK)

    assert counts["entries_created"] == 1
    assert counts["digests_sent"] == 0


@pytest.mark.anyio
async def test_one_organizations_failure_does_not_stop_the_rest():
    """Mining failing for one org must not silence the next org's digest."""
    first, second = _org("First"), _org("Second")
    service = _service([_pattern()])
    service.list_org_patterns = AsyncMock(
        side_effect=[
            RuntimeError("mining down"),
            FailurePatternList(items=[_pattern()], total=1, notes=[]),
        ]
    )
    mail = _mail()

    with (
        patch(
            f"{MODULE}.settings",
            SimpleNamespace(FAILURE_LEARNING_DIGEST_RECIPIENT="ops@example.test"),
        ),
        patch(f"{MODULE}.get_db_context", _fake_db_context),
        patch(
            f"{MODULE}.organization_repo.list_all",
            new=AsyncMock(return_value=[first, second]),
        ),
        patch(f"{MODULE}.FailureLearningService", return_value=service),
        patch(f"{MODULE}.get_email_service", return_value=mail),
    ):
        counts = await failure_ledger_digest(_TICK)

    assert counts["entries_created"] == 1
    assert counts["digests_sent"] == 1
    assert mail.send.await_args.kwargs["context"]["org_name"] == "Second"
