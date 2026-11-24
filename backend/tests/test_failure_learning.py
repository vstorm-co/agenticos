"""The failure-learning loop's service, with its dependencies mocked.

Mining is a live aggregation, so the mining tests stand in the repository
rows - what the service does with them (thresholds, merging, marking) is
what is asserted here. The repository queries themselves are proved
against Postgres in `tests/integration/test_failure_learning.py`.
"""

import hashlib
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AlreadyExistsError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.permissions import AuthContext
from app.repositories import (
    agent_repo,
    agent_run_repo,
    conversation_repo,
    credential_repo,
    failure_learning_repo,
)
from app.repositories.agent_run import DownRatedRow, FailureGroupRow
from app.schemas.eval_judging import EvalExpectation
from app.schemas.failure_learning import (
    EvalCaseCreate,
    EvalCaseInput,
    EvalTryCreate,
    LedgerEntryCreate,
    LedgerEntryUpdate,
    ProposalCreate,
    ProposalReject,
    ProposalTarget,
)
from app.services import rate_limit as rate_limit_module
from app.services.failure_learning import (
    HANG_NOTE,
    MODEL_NOTE,
    FailureLearningService,
    _history_messages,
    _window,
    parse_error_class,
    pattern_key_for,
)
from app.services.rate_limit import Decision

pytestmark = pytest.mark.anyio

_NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")


def _agent(**overrides):
    agent = MagicMock(
        id=uuid4(),
        organization_id=uuid4(),
        name="Support",
        status="published",
        current_version_id=uuid4(),
    )
    for name, value in overrides.items():
        setattr(agent, name, value)
    return agent


def _service(mock_db_session) -> FailureLearningService:
    service = FailureLearningService(mock_db_session)
    service.registry.get = AsyncMock(return_value=_agent())
    return service


def _group(agent_id, **overrides):
    values = {
        "agent_id": agent_id,
        "model_label": "anthropic:claude-sonnet-4-5",
        "status": "failed",
        "error": "The run did not finish (ModelHTTPError, HTTP 400) - retry it.",
        "count": 3,
        "first_seen": _NOW - timedelta(days=2),
        "last_seen": _NOW - timedelta(hours=1),
    }
    values.update(overrides)
    return FailureGroupRow(**values)


def _case_row(agent_id, **overrides):
    row = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        agent_id=agent_id,
        ledger_entry_id=None,
        name="Refund loop",
        position=1,
        input={"message": "Refund me", "history": []},
        expectation={"kind": "not_contains", "field": "text", "value": "draft"},
        model_profile_id=None,
        source_run_id=None,
        created_by_user_id=uuid4(),
        created_at=_NOW,
        updated_at=None,
    )
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


def _proposal_row(agent_id, **overrides):
    row = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        agent_id=agent_id,
        ledger_entry_id=None,
        eval_try_id=None,
        target_type="instructions",
        skill_id=None,
        old_text="Draft a PR.",
        new_text="Never draft a PR.",
        rationale="The agent drafts when told to publish.",
        base_agent_version_id=uuid4(),
        base_content_sha256=None,
        prior_skill_content=None,
        applied_content_sha256=None,
        reverted_by_user_id=None,
        reverted_at=None,
        status="draft",
        applied_version_id=None,
        created_by_user_id=uuid4(),
        decided_by_user_id=None,
        decided_at=None,
        created_at=_NOW,
        updated_at=None,
    )
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


def _entry_row(agent_id, **overrides):
    row = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        agent_id=agent_id,
        scope="agent",
        model=None,
        pattern_key="failed:ModelHTTPError:400",
        title="400s on refunds",
        summary="Keeps failing on refund asks.",
        evidence={"count": 3},
        status="draft",
        created_by_user_id=uuid4(),
        created_at=_NOW,
        updated_at=None,
    )
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


class TestParseErrorClass:
    def test_model_http_errors_keep_their_status_code(self):
        assert (
            parse_error_class(
                "The run did not finish (ModelHTTPError, HTTP 429) - retry it.", "failed"
            )
            == "ModelHTTPError:429"
        )

    def test_expiry_sentences_are_their_own_classes(self):
        assert parse_error_class(
            "No decision within 72h - the parked tool call expired", "cancelled"
        ) == ("approval_expired")
        assert parse_error_class("No answer within 24h - the question expired", "cancelled") == (
            "question_expired"
        )

    def test_stops_are_classes_not_failures(self):
        assert parse_error_class(None, "loop_stopped") == "loop_stopped"
        assert parse_error_class(None, "budget_exceeded") == "budget_exceeded"

    def test_an_unknown_sentence_is_other_not_a_guess(self):
        assert parse_error_class("Something odd happened", "failed") == "other"
        assert parse_error_class(None, "failed") == "other"

    def test_pattern_keys(self):
        assert pattern_key_for("failed", "ModelHTTPError:400") == "failed:ModelHTTPError:400"
        assert pattern_key_for("cancelled", "approval_expired") == "approval_expired"
        assert pattern_key_for("failed", "other") == "failed:other"

    def test_a_usage_limit_is_its_own_class(self):
        assert (
            parse_error_class("UsageLimitExceeded: the plan is spent", "failed")
            == "UsageLimitExceeded"
        )

    def test_a_non_failed_status_keeps_its_prefix(self):
        assert pattern_key_for("cancelled", "other") == "cancelled:other"


class TestWindow:
    def test_defaults_to_the_last_seven_days(self):
        start, end = _window(None, None)
        assert (end - start).days == 7

    def test_a_reversed_window_is_refused(self):
        with pytest.raises(ValidationError):
            _window(date(2026, 11, 10), date(2026, 11, 9))


class TestHistoryMessages:
    def test_user_and_assistant_turns_become_model_messages(self):
        messages = _history_messages(
            {"history": [{"role": "user", "text": "Hi"}, {"role": "assistant", "text": "Hello"}]}
        )
        assert len(messages) == 2
        assert messages[0].parts[0].content == "Hi"
        assert messages[1].parts[0].content == "Hello"


class TestMining:
    async def test_a_pattern_below_threshold_does_not_surface(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent_id = uuid4()
        monkeypatch.setattr(
            agent_run_repo, "failure_groups", AsyncMock(return_value=[_group(agent_id, count=2)])
        )
        monkeypatch.setattr(agent_run_repo, "failure_group_samples", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=[]))
        monkeypatch.setattr(failure_learning_repo, "open_entries", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        patterns = await service.list_agent_patterns(_ctx(), agent_id)

        assert patterns.total == 0

    async def test_sentences_merge_into_one_class_with_sample_runs(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent_id = uuid4()
        run_id = uuid4()
        monkeypatch.setattr(
            agent_run_repo,
            "failure_groups",
            AsyncMock(
                return_value=[
                    _group(agent_id, count=2),
                    _group(
                        agent_id,
                        count=2,
                        error="The run did not finish (ModelHTTPError, HTTP 400).",
                    ),
                ]
            ),
        )
        monkeypatch.setattr(
            agent_run_repo, "failure_group_samples", AsyncMock(return_value=[run_id])
        )
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=[]))
        monkeypatch.setattr(failure_learning_repo, "open_entries", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        patterns = await service.list_agent_patterns(_ctx(), agent_id)

        assert patterns.total == 1
        pattern = patterns.items[0]
        assert pattern.count == 4
        assert pattern.error_class == "ModelHTTPError:400"
        assert pattern.pattern_key == "failed:ModelHTTPError:400"
        assert run_id in pattern.sample_run_ids
        assert pattern.already_tracked is False
        assert HANG_NOTE in patterns.notes and MODEL_NOTE in patterns.notes

    async def test_an_open_entry_marks_its_pattern_tracked(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent_id = uuid4()
        monkeypatch.setattr(
            agent_run_repo, "failure_groups", AsyncMock(return_value=[_group(agent_id)])
        )
        monkeypatch.setattr(agent_run_repo, "failure_group_samples", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            failure_learning_repo,
            "open_entries",
            AsyncMock(return_value=[_entry_row(agent_id, status="open")]),
        )
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        patterns = await service.list_agent_patterns(_ctx(), agent_id)

        assert patterns.items[0].already_tracked is True

    async def test_a_stalled_run_surfaces_on_its_own(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent_id = uuid4()
        stalled = SimpleNamespace(
            id=uuid4(),
            agent_id=agent_id,
            model_label="anthropic:claude-sonnet-4-5",
            started_at=_NOW - timedelta(minutes=30),
        )
        monkeypatch.setattr(agent_run_repo, "failure_groups", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[stalled]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=[]))
        monkeypatch.setattr(failure_learning_repo, "open_entries", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        patterns = await service.list_agent_patterns(_ctx(), agent_id)

        assert patterns.total == 1
        assert patterns.items[0].error_class == "stalled"
        assert patterns.items[0].status == "running"

    async def test_down_rated_answers_need_three_and_carry_message_ids(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent_id = uuid4()
        rows = [
            DownRatedRow(
                run_id=uuid4(),
                agent_id=agent_id,
                model_label="anthropic:claude-sonnet-4-5",
                message_id=uuid4(),
                rated_at=_NOW - timedelta(days=1),
            )
            for _ in range(3)
        ]
        monkeypatch.setattr(agent_run_repo, "failure_groups", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=rows))
        monkeypatch.setattr(failure_learning_repo, "open_entries", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        patterns = await service.list_agent_patterns(_ctx(), agent_id)

        assert patterns.total == 1
        pattern = patterns.items[0]
        assert pattern.error_class == "downrated"
        assert len(pattern.sample_message_ids) == 3
        assert len(pattern.sample_run_ids) == 3

    async def test_a_model_pattern_needs_five_across_agents(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        monkeypatch.setattr(
            agent_run_repo,
            "failure_groups",
            AsyncMock(return_value=[_group(uuid4(), count=3), _group(uuid4(), count=3)]),
        )
        monkeypatch.setattr(agent_run_repo, "failure_group_samples", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=[]))
        monkeypatch.setattr(failure_learning_repo, "open_entries", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        patterns = await service.list_org_patterns(_ctx())

        model_patterns = [p for p in patterns.items if p.agent_id is None]
        assert len(model_patterns) == 1
        assert model_patterns[0].count == 6

    async def test_model_threshold_counts_failures_below_each_agent_threshold(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        monkeypatch.setattr(
            agent_run_repo,
            "failure_groups",
            AsyncMock(
                return_value=[
                    _group(uuid4(), count=2),
                    _group(uuid4(), count=2),
                    _group(uuid4(), count=1),
                ]
            ),
        )
        monkeypatch.setattr(agent_run_repo, "failure_group_samples", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=[]))
        monkeypatch.setattr(failure_learning_repo, "open_entries", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        patterns = await service.list_org_patterns(_ctx())

        model_patterns = [pattern for pattern in patterns.items if pattern.agent_id is None]
        agent_patterns = [pattern for pattern in patterns.items if pattern.agent_id is not None]
        assert len(model_patterns) == 1
        assert model_patterns[0].count == 5
        assert agent_patterns == []

    async def test_model_and_status_filters_narrow_the_list(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent_id = uuid4()
        monkeypatch.setattr(
            agent_run_repo, "failure_groups", AsyncMock(return_value=[_group(agent_id)])
        )
        monkeypatch.setattr(agent_run_repo, "failure_group_samples", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=[]))
        monkeypatch.setattr(failure_learning_repo, "open_entries", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        assert (await service.list_agent_patterns(_ctx(), agent_id, model="other-model")).total == 0
        assert (await service.list_agent_patterns(_ctx(), agent_id, status="completed")).total == 0
        assert (
            await service.list_agent_patterns(_ctx(), agent_id, model="anthropic:claude-sonnet-4-5")
        ).total == 1

    async def test_duplicate_group_rows_merge_their_window(self, monkeypatch, mock_db_session):
        """Two rows for one key merge counts and widen the window to the extremes."""
        service = _service(mock_db_session)
        agent_id = uuid4()
        monkeypatch.setattr(
            agent_run_repo,
            "failure_groups",
            AsyncMock(
                return_value=[
                    _group(
                        agent_id,
                        count=2,
                        first_seen=_NOW - timedelta(days=1),
                        last_seen=_NOW - timedelta(days=2),
                    ),
                    _group(
                        agent_id,
                        count=2,
                        error="The run did not finish (ModelHTTPError, HTTP 400).",
                        first_seen=_NOW - timedelta(days=3),
                        last_seen=_NOW - timedelta(hours=1),
                    ),
                ]
            ),
        )
        monkeypatch.setattr(agent_run_repo, "failure_group_samples", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=[]))
        monkeypatch.setattr(failure_learning_repo, "open_entries", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        patterns = await service.list_agent_patterns(_ctx(), agent_id)

        assert patterns.total == 1
        pattern = patterns.items[0]
        assert pattern.count == 4
        assert pattern.first_seen == _NOW - timedelta(days=3)
        assert pattern.last_seen == _NOW - timedelta(hours=1)

    async def test_a_model_total_below_five_adds_no_model_pattern(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        monkeypatch.setattr(
            agent_run_repo,
            "failure_groups",
            AsyncMock(return_value=[_group(uuid4(), count=3), _group(uuid4(), count=1)]),
        )
        monkeypatch.setattr(agent_run_repo, "failure_group_samples", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=[]))
        monkeypatch.setattr(failure_learning_repo, "open_entries", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        patterns = await service.list_org_patterns(_ctx())

        assert patterns.total == 1
        assert all(pattern.agent_id is not None for pattern in patterns.items)

    async def test_two_down_rated_answers_are_not_a_pattern(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent_id = uuid4()
        rows = [
            DownRatedRow(
                run_id=uuid4(),
                agent_id=agent_id,
                model_label="anthropic:claude-sonnet-4-5",
                message_id=uuid4(),
                rated_at=_NOW - timedelta(days=1),
            )
            for _ in range(2)
        ]
        monkeypatch.setattr(agent_run_repo, "failure_groups", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=rows))
        monkeypatch.setattr(failure_learning_repo, "open_entries", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        patterns = await service.list_agent_patterns(_ctx(), agent_id)

        assert patterns.total == 0

    async def test_an_entry_for_another_pattern_does_not_mark_it(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent_id = uuid4()
        monkeypatch.setattr(
            agent_run_repo, "failure_groups", AsyncMock(return_value=[_group(agent_id)])
        )
        monkeypatch.setattr(agent_run_repo, "failure_group_samples", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            failure_learning_repo,
            "open_entries",
            AsyncMock(return_value=[_entry_row(agent_id, pattern_key="failed:ModelHTTPError:500")]),
        )
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        patterns = await service.list_agent_patterns(_ctx(), agent_id)

        assert patterns.items[0].already_tracked is False

    async def test_an_entry_for_another_agent_does_not_mark_it(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent_id = uuid4()
        monkeypatch.setattr(
            agent_run_repo, "failure_groups", AsyncMock(return_value=[_group(agent_id)])
        )
        monkeypatch.setattr(agent_run_repo, "failure_group_samples", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            failure_learning_repo,
            "open_entries",
            AsyncMock(return_value=[_entry_row(uuid4())]),
        )
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        patterns = await service.list_agent_patterns(_ctx(), agent_id)

        assert patterns.items[0].already_tracked is False

    async def test_an_open_model_entry_marks_its_model_pattern_tracked(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        monkeypatch.setattr(
            agent_run_repo,
            "failure_groups",
            AsyncMock(return_value=[_group(uuid4(), count=3), _group(uuid4(), count=3)]),
        )
        monkeypatch.setattr(agent_run_repo, "failure_group_samples", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            failure_learning_repo,
            "open_entries",
            AsyncMock(
                return_value=[
                    _entry_row(
                        None, scope="model", model="anthropic:claude-sonnet-4-5", status="open"
                    )
                ]
            ),
        )
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        patterns = await service.list_org_patterns(_ctx())

        model_patterns = [p for p in patterns.items if p.agent_id is None]
        assert len(model_patterns) == 1
        assert model_patterns[0].already_tracked is True
        assert all(p.already_tracked is False for p in patterns.items if p.agent_id is not None)

    async def test_an_agent_entry_does_not_cover_a_model_pattern(
        self, monkeypatch, mock_db_session
    ):
        """Same key, wrong scope: a model pattern needs a model entry, not an agent's."""
        service = _service(mock_db_session)
        monkeypatch.setattr(
            agent_run_repo,
            "failure_groups",
            AsyncMock(return_value=[_group(uuid4(), count=3), _group(uuid4(), count=3)]),
        )
        monkeypatch.setattr(agent_run_repo, "failure_group_samples", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            failure_learning_repo,
            "open_entries",
            AsyncMock(return_value=[_entry_row(uuid4(), status="open")]),
        )
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        patterns = await service.list_org_patterns(_ctx())

        assert all(p.already_tracked is False for p in patterns.items)
        assert all(p.already_tracked is False for p in patterns.items if p.agent_id is not None)


class TestLedger:
    async def test_creating_an_agent_entry(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(failure_learning_repo, "list_entries", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            failure_learning_repo, "create_entry", AsyncMock(return_value=_entry_row(agent.id))
        )
        monkeypatch.setattr(
            failure_learning_repo, "count_cases_for_entry", AsyncMock(return_value=0)
        )
        monkeypatch.setattr(
            failure_learning_repo, "count_proposals_for_entry", AsyncMock(return_value=0)
        )

        entry = await service.create_ledger(
            _ctx(),
            agent.id,
            LedgerEntryCreate(
                scope="agent",
                pattern_key="failed:ModelHTTPError:400",
                title="400s on refunds",
                summary="Keeps failing.",
                evidence={"count": 3},
            ),
        )

        assert entry.agent_id == agent.id
        assert entry.status == "draft"

    async def test_a_model_entry_without_a_model_is_refused(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        with pytest.raises(BadRequestError):
            await service.create_ledger(
                _ctx(),
                agent.id,
                LedgerEntryCreate(
                    scope="model",
                    pattern_key="failed:ModelHTTPError:400",
                    title="400s",
                    summary="Keeps failing.",
                ),
            )

    async def test_a_second_open_entry_for_the_same_pattern_is_refused(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(
            failure_learning_repo,
            "list_entries",
            AsyncMock(return_value=[_entry_row(agent.id, status="open")]),
        )
        with pytest.raises(AlreadyExistsError):
            await service.create_ledger(
                _ctx(),
                agent.id,
                LedgerEntryCreate(
                    scope="agent",
                    pattern_key="failed:ModelHTTPError:400",
                    title="400s again",
                    summary="Keeps failing.",
                ),
            )

    async def test_getting_an_entry_reports_its_case_count(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        entry_id = uuid4()
        monkeypatch.setattr(
            failure_learning_repo,
            "get_entry",
            AsyncMock(return_value=_entry_row(agent.id, id=entry_id)),
        )
        monkeypatch.setattr(
            failure_learning_repo, "count_cases_for_entry", AsyncMock(return_value=2)
        )
        monkeypatch.setattr(
            failure_learning_repo, "count_proposals_for_entry", AsyncMock(return_value=1)
        )

        entry = await service.get_ledger(_ctx(), agent.id, entry_id)

        assert entry.id == entry_id
        assert entry.eval_case_count == 2
        assert entry.proposal_count == 1

    async def test_listing_an_agent_lists_its_model_entries_too(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        own = _entry_row(agent.id, created_at=_NOW - timedelta(hours=1))
        model_wide = _entry_row(
            None, scope="model", model="anthropic:claude-sonnet-4-5", created_at=_NOW
        )

        async def _list_entries(_db, *, organization_id, agent_id, status=None):
            return [own] if agent_id is not None else [model_wide]

        monkeypatch.setattr(failure_learning_repo, "list_entries", _list_entries)
        monkeypatch.setattr(
            failure_learning_repo, "count_cases_for_entry", AsyncMock(return_value=0)
        )
        monkeypatch.setattr(
            failure_learning_repo, "count_proposals_for_entry", AsyncMock(return_value=0)
        )

        listed = await service.list_ledger(_ctx(), agent.id)

        assert listed.total == 2
        assert listed.items[0].scope == "model"
        assert listed.items[1].scope == "agent"

    async def test_accepting_an_entry_is_a_curated_change(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(
            failure_learning_repo, "get_entry", AsyncMock(return_value=_entry_row(agent.id))
        )
        monkeypatch.setattr(
            failure_learning_repo,
            "update_entry",
            AsyncMock(return_value=_entry_row(agent.id, status="open")),
        )
        monkeypatch.setattr(
            failure_learning_repo, "count_cases_for_entry", AsyncMock(return_value=0)
        )
        monkeypatch.setattr(
            failure_learning_repo, "count_proposals_for_entry", AsyncMock(return_value=0)
        )

        entry = await service.update_ledger(
            _ctx(), agent.id, uuid4(), LedgerEntryUpdate(status="open")
        )

        assert entry.status == "open"

    async def test_deleting_an_entry_removes_it(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(
            failure_learning_repo, "get_entry", AsyncMock(return_value=_entry_row(agent.id))
        )
        deleted = AsyncMock()
        monkeypatch.setattr(failure_learning_repo, "delete_entry", deleted)

        await service.delete_ledger(_ctx(), agent.id, uuid4())

        deleted.assert_awaited_once()

    async def test_getting_a_missing_entry_is_not_found(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(failure_learning_repo, "get_entry", AsyncMock(return_value=None))
        with pytest.raises(NotFoundError):
            await service.get_ledger(_ctx(), agent.id, uuid4())

    async def test_resolving_by_hand_is_refused(self, monkeypatch, mock_db_session):
        """Only an apply resolves an entry - a status change to resolved is refused."""
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(
            failure_learning_repo, "get_entry", AsyncMock(return_value=_entry_row(agent.id))
        )
        with pytest.raises(BadRequestError):
            await service.update_ledger(
                _ctx(), agent.id, uuid4(), LedgerEntryUpdate(status="resolved")
            )

    async def test_deleting_a_missing_entry_is_not_found(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(failure_learning_repo, "get_entry", AsyncMock(return_value=None))
        with pytest.raises(NotFoundError):
            await service.delete_ledger(_ctx(), agent.id, uuid4())


class TestCases:
    def _create(self, **overrides):
        values = {
            "name": "Refund loop",
            "input": EvalCaseInput(message="Refund me"),
            "expectation": EvalExpectation(kind="not_contains", field="text", value="draft"),
        }
        values.update(overrides)
        return EvalCaseCreate(**values)

    async def test_creating_a_case(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(failure_learning_repo, "count_cases", AsyncMock(return_value=0))
        monkeypatch.setattr(failure_learning_repo, "last_position", AsyncMock(return_value=0))
        monkeypatch.setattr(
            failure_learning_repo, "create_case", AsyncMock(return_value=_case_row(agent.id))
        )

        case = await service.create_case(_ctx(), agent.id, self._create())

        assert case.name == "Refund loop"
        assert case.position == 1

    async def test_the_fiftieth_case_is_the_last(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(failure_learning_repo, "count_cases", AsyncMock(return_value=50))
        with pytest.raises(BadRequestError):
            await service.create_case(_ctx(), agent.id, self._create())

    async def test_a_case_on_another_agents_ledger_is_not_found(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(failure_learning_repo, "count_cases", AsyncMock(return_value=0))
        monkeypatch.setattr(failure_learning_repo, "get_entry", AsyncMock(return_value=None))
        with pytest.raises(NotFoundError):
            await service.create_case(_ctx(), agent.id, self._create(ledger_entry_id=uuid4()))

    async def test_a_case_on_a_run_of_another_agent_is_not_found(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(failure_learning_repo, "count_cases", AsyncMock(return_value=0))
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(return_value=SimpleNamespace(agent_id=uuid4())),
        )
        with pytest.raises(NotFoundError):
            await service.create_case(_ctx(), agent.id, self._create(source_run_id=uuid4()))

    async def test_listing_cases_carries_the_latest_trys_verdict(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        case = _case_row(agent.id)
        other = _case_row(agent.id, name="Second case")
        old_run, new_run = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
        monkeypatch.setattr(
            failure_learning_repo, "list_cases", AsyncMock(return_value=[case, other])
        )
        # The latest run tried only the first case; the second has no verdict.
        monkeypatch.setattr(
            failure_learning_repo,
            "latest_run",
            AsyncMock(
                return_value=_created_run(
                    mock_db_session,
                    agent_id=agent.id,
                    organization_id=uuid4(),
                    cases=[
                        {
                            "eval_id": str(case.id),
                            "name": case.name,
                            "expectation": case.expectation,
                            "old_run_ids": [str(old_run.id)],
                            "new_run_ids": [str(new_run.id)],
                            "samples": 1,
                            "refused": None,
                        }
                    ],
                )
            ),
        )
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(
                side_effect=[
                    SimpleNamespace(id=old_run.id, status="failed"),
                    SimpleNamespace(id=new_run.id, status="completed"),
                ]
            ),
        )
        monkeypatch.setattr(
            conversation_repo, "last_answer_of_run", AsyncMock(return_value="Here is the refund.")
        )
        listed = await service.list_cases(_ctx(), agent.id)

        assert listed.total == 2
        assert listed.items[0].latest_try is not None
        assert listed.items[0].latest_try.gate_passed is True
        assert listed.items[1].latest_try is None

    async def test_listing_cases_without_a_try_has_no_verdict(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(
            failure_learning_repo,
            "list_cases",
            AsyncMock(return_value=[_case_row(agent.id)]),
        )
        monkeypatch.setattr(failure_learning_repo, "latest_run", AsyncMock(return_value=None))

        listed = await service.list_cases(_ctx(), agent.id)

        assert listed.total == 1
        assert listed.items[0].latest_try is None

    async def test_creating_a_case_on_the_agents_own_run(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(failure_learning_repo, "count_cases", AsyncMock(return_value=0))
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(return_value=SimpleNamespace(agent_id=agent.id)),
        )
        monkeypatch.setattr(failure_learning_repo, "last_position", AsyncMock(return_value=0))
        monkeypatch.setattr(
            failure_learning_repo, "create_case", AsyncMock(return_value=_case_row(agent.id))
        )

        case = await service.create_case(_ctx(), agent.id, self._create(source_run_id=uuid4()))

        assert case.name == "Refund loop"

    async def test_a_case_naming_a_missing_model_profile_is_not_found(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(failure_learning_repo, "count_cases", AsyncMock(return_value=0))
        monkeypatch.setattr(credential_repo, "get_profile", AsyncMock(return_value=None))
        with pytest.raises(NotFoundError):
            await service.create_case(_ctx(), agent.id, self._create(model_profile_id=uuid4()))

    async def test_creating_a_case_with_a_known_model_profile(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(failure_learning_repo, "count_cases", AsyncMock(return_value=0))
        monkeypatch.setattr(
            credential_repo, "get_profile", AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        )
        monkeypatch.setattr(failure_learning_repo, "last_position", AsyncMock(return_value=0))
        monkeypatch.setattr(
            failure_learning_repo, "create_case", AsyncMock(return_value=_case_row(agent.id))
        )

        case = await service.create_case(_ctx(), agent.id, self._create(model_profile_id=uuid4()))

        assert case.name == "Refund loop"

    async def test_deleting_a_case_removes_it(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(
            failure_learning_repo, "get_case", AsyncMock(return_value=_case_row(agent.id))
        )
        deleted = AsyncMock()
        monkeypatch.setattr(failure_learning_repo, "delete_case", deleted)

        await service.delete_case(_ctx(), agent.id, uuid4())

        deleted.assert_awaited_once()

    async def test_deleting_a_missing_case_is_not_found(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(failure_learning_repo, "get_case", AsyncMock(return_value=None))
        with pytest.raises(NotFoundError):
            await service.delete_case(_ctx(), agent.id, uuid4())


def _created_run(_db, **fields):
    """A try row holding the entries the service tried, as the repository would."""
    return SimpleNamespace(
        id=uuid4(),
        agent_id=fields["agent_id"],
        organization_id=fields["organization_id"],
        proposal_id=fields.get("proposal_id"),
        target_skill_id=fields.get("target_skill_id"),
        tested_content_sha256=fields.get("tested_content_sha256"),
        created_at=_NOW,
        cases=fields["cases"],
    )


class TestTries:
    def _setup_try(self, service, monkeypatch, *, case=None, agent=None):
        agent = agent or service.registry.get.return_value
        case = case or _case_row(agent.id)
        monkeypatch.setattr(
            failure_learning_repo, "get_cases_by_ids", AsyncMock(return_value=[case])
        )
        version = SimpleNamespace(
            spec=AgentSpec(name="Support", model_profile_id=uuid4()).model_dump(mode="json")
        )
        monkeypatch.setattr(agent_repo, "get_version", AsyncMock(return_value=version))
        monkeypatch.setattr(
            rate_limit_module,
            "consume",
            AsyncMock(return_value=Decision(allowed=True, retry_after_seconds=0)),
        )
        service.conversations.create_conversation = AsyncMock(
            return_value=SimpleNamespace(id=uuid4())
        )
        return agent, case

    async def test_a_try_naming_a_proposal_tries_its_text(self, monkeypatch, mock_db_session):
        """A try naming a draft instruction proposal runs the proposal's new text."""
        service = _service(mock_db_session)
        agent, case = self._setup_try(service, monkeypatch)
        proposal = _proposal_row(agent.id, new_text="Never draft.")
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        old_run, new_run = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
        service.runner.execute = AsyncMock(
            side_effect=[("old answer", old_run), ("new answer", new_run)]
        )
        monkeypatch.setattr(
            failure_learning_repo, "create_run", AsyncMock(side_effect=_created_run)
        )
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(
                side_effect=[
                    SimpleNamespace(id=old_run.id, status="failed"),
                    SimpleNamespace(id=new_run.id, status="completed"),
                ]
            ),
        )
        monkeypatch.setattr(
            conversation_repo, "last_answer_of_run", AsyncMock(return_value="Here is the refund.")
        )
        linked = AsyncMock()
        monkeypatch.setattr(failure_learning_repo, "update_proposal", linked)

        tried = await service.start_try(
            _ctx(), agent.id, EvalTryCreate(case_ids=[case.id], proposal_id=proposal.id)
        )

        assert tried.proposal_id == proposal.id
        assert tried.tested_content_sha256 == hashlib.sha256(b"Never draft.").hexdigest()
        linked.assert_awaited_once()
        assert linked.await_args.kwargs["update_data"]["eval_try_id"] == tried.id
        calls = service.runner.execute.await_args_list
        assert calls[1].kwargs["instructions_override"] == "Never draft."

    async def test_a_try_naming_both_a_proposal_and_an_override_is_refused(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        with pytest.raises(BadRequestError):
            await service.start_try(
                _ctx(),
                uuid4(),
                EvalTryCreate(
                    case_ids=[uuid4()],
                    proposal_id=uuid4(),
                    instructions_override="New text.",
                ),
            )

    async def test_a_try_naming_a_skill_proposal_overrides_only_the_test_run(
        self, monkeypatch, mock_db_session
    ):
        import hashlib

        service = _service(mock_db_session)
        agent, case = self._setup_try(service, monkeypatch)
        skill_id = uuid4()
        spec = AgentSpec(name="Support", model_profile_id=uuid4()).model_dump(mode="json")
        spec["skill_ids"] = [str(skill_id)]
        monkeypatch.setattr(
            agent_repo, "get_version", AsyncMock(return_value=SimpleNamespace(spec=spec))
        )
        skill = SimpleNamespace(id=skill_id, content="Current skill text.")
        service.skills.get = AsyncMock(return_value=skill)
        proposal = _proposal_row(
            agent.id,
            target_type="skill",
            skill_id=skill_id,
            new_text="Proposed skill text.",
            base_content_sha256=hashlib.sha256(b"Current skill text.").hexdigest(),
        )
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        old_run, new_run = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
        service.runner.execute = AsyncMock(side_effect=[("old", old_run), ("new", new_run)])
        monkeypatch.setattr(
            failure_learning_repo, "create_run", AsyncMock(side_effect=_created_run)
        )
        linked = AsyncMock()
        monkeypatch.setattr(failure_learning_repo, "update_proposal", linked)
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(
                side_effect=[
                    SimpleNamespace(id=old_run.id, status="failed"),
                    SimpleNamespace(id=new_run.id, status="completed"),
                ]
            ),
        )
        monkeypatch.setattr(conversation_repo, "last_answer_of_run", AsyncMock(return_value="safe"))

        tried = await service.start_try(
            _ctx(), agent.id, EvalTryCreate(case_ids=[case.id], proposal_id=proposal.id)
        )

        assert tried.target_skill_id == skill_id
        assert tried.tested_content_sha256 == hashlib.sha256(b"Proposed skill text.").hexdigest()
        assert service.runner.execute.await_args_list[0].kwargs["skill_content_overrides"] is None
        assert service.runner.execute.await_args_list[1].kwargs["skill_content_overrides"] == {
            skill_id: "Proposed skill text."
        }
        assert linked.await_args.kwargs["update_data"]["eval_try_id"] == tried.id

    def test_eval_try_rejects_more_than_ten_agent_runs(self):
        with pytest.raises(PydanticValidationError, match="at most 10 agent runs"):
            EvalTryCreate(case_ids=[uuid4() for _ in range(6)])

    def test_eval_try_allows_ten_agent_runs(self):
        assert len(EvalTryCreate(case_ids=[uuid4()], samples=5).case_ids) == 1

    async def test_a_try_naming_a_decided_proposal_is_refused(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        proposal = _proposal_row(agent.id, status="applied")
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        with pytest.raises(BadRequestError):
            await service.start_try(
                _ctx(), agent.id, EvalTryCreate(case_ids=[uuid4()], proposal_id=proposal.id)
            )

    async def test_a_try_naming_a_missing_proposal_is_not_found(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=None))
        with pytest.raises(NotFoundError):
            await service.start_try(
                _ctx(), uuid4(), EvalTryCreate(case_ids=[uuid4()], proposal_id=uuid4())
            )

    async def test_a_try_with_no_new_text_is_refused(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        with pytest.raises(BadRequestError):
            await service.start_try(_ctx(), uuid4(), EvalTryCreate(case_ids=[uuid4()]))

    async def test_a_try_on_an_archived_agent_is_refused(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = _agent(status="archived")
        service.registry.get = AsyncMock(return_value=agent)
        self._setup_try(service, monkeypatch, agent=agent)
        with pytest.raises(BadRequestError):
            await service.start_try(
                _ctx(),
                agent.id,
                EvalTryCreate(case_ids=[uuid4()], instructions_override="New text."),
            )

    async def test_a_try_on_an_agent_pointing_at_a_missing_version_is_refused(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent, case = self._setup_try(service, monkeypatch)
        monkeypatch.setattr(agent_repo, "get_version", AsyncMock(return_value=None))
        with pytest.raises(BadRequestError):
            await service.start_try(
                _ctx(),
                agent.id,
                EvalTryCreate(case_ids=[case.id], instructions_override="New text."),
            )

    async def test_a_run_that_started_and_then_failed_is_judged_not_refused(
        self, monkeypatch, mock_db_session
    ):
        """A run that opened and then failed still has a row to judge."""
        service = _service(mock_db_session)
        agent, case = self._setup_try(service, monkeypatch)
        old_run, new_run = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())

        async def _execute(*_args, **kwargs):
            if _execute.calls == 0:
                _execute.calls += 1
                await kwargs["on_run_open"](old_run)
                raise BadRequestError(message="Monthly budget spent")
            return ("new answer", new_run)

        _execute.calls = 0
        service.runner.execute = AsyncMock(side_effect=_execute)
        monkeypatch.setattr(
            failure_learning_repo, "create_run", AsyncMock(side_effect=_created_run)
        )
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(
                side_effect=[
                    SimpleNamespace(id=old_run.id, status="failed"),
                    SimpleNamespace(id=new_run.id, status="completed"),
                ]
            ),
        )
        monkeypatch.setattr(
            conversation_repo, "last_answer_of_run", AsyncMock(return_value="Here is the refund.")
        )

        tried = await service.start_try(
            _ctx(),
            agent.id,
            EvalTryCreate(case_ids=[case.id], instructions_override="Never draft."),
            first_run_charged=True,
        )

        assert tried.cases[0].old_run_ids == [old_run.id]
        assert tried.cases[0].reason is None
        assert tried.cases[0].gate_passed is True

    async def test_a_removed_run_cannot_pass(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent, case = self._setup_try(service, monkeypatch)
        old_run, new_run = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
        service.runner.execute = AsyncMock(
            side_effect=[("old answer", old_run), ("new answer", new_run)]
        )
        monkeypatch.setattr(
            failure_learning_repo, "create_run", AsyncMock(side_effect=_created_run)
        )
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(
                side_effect=[
                    None,
                    SimpleNamespace(id=new_run.id, status="completed"),
                ]
            ),
        )
        monkeypatch.setattr(
            conversation_repo, "last_answer_of_run", AsyncMock(return_value="Here is the refund.")
        )

        tried = await service.start_try(
            _ctx(),
            agent.id,
            EvalTryCreate(case_ids=[case.id], instructions_override="Never draft."),
            first_run_charged=True,
        )

        assert tried.cases[0].old_passed is False
        assert tried.cases[0].gate_passed is True

    async def test_a_completed_run_with_no_answer_cannot_pass(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent, case = self._setup_try(service, monkeypatch)
        old_run, new_run = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
        service.runner.execute = AsyncMock(
            side_effect=[("old answer", old_run), ("new answer", new_run)]
        )
        monkeypatch.setattr(
            failure_learning_repo, "create_run", AsyncMock(side_effect=_created_run)
        )
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(
                side_effect=[
                    SimpleNamespace(id=old_run.id, status="failed"),
                    SimpleNamespace(id=new_run.id, status="completed"),
                ]
            ),
        )
        monkeypatch.setattr(conversation_repo, "last_answer_of_run", AsyncMock(return_value=None))

        tried = await service.start_try(
            _ctx(),
            agent.id,
            EvalTryCreate(case_ids=[case.id], instructions_override="Never draft."),
            first_run_charged=True,
        )

        assert tried.cases[0].new_passed is False
        assert tried.cases[0].gate_passed is False

    async def test_an_answer_that_fails_the_expectation_cannot_pass(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent, case = self._setup_try(service, monkeypatch)
        old_run, new_run = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
        service.runner.execute = AsyncMock(
            side_effect=[("old answer", old_run), ("new answer", new_run)]
        )
        monkeypatch.setattr(
            failure_learning_repo, "create_run", AsyncMock(side_effect=_created_run)
        )
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(
                side_effect=[
                    SimpleNamespace(id=old_run.id, status="failed"),
                    SimpleNamespace(id=new_run.id, status="completed"),
                ]
            ),
        )
        monkeypatch.setattr(
            conversation_repo, "last_answer_of_run", AsyncMock(return_value="Here is the draft.")
        )

        tried = await service.start_try(
            _ctx(),
            agent.id,
            EvalTryCreate(case_ids=[case.id], instructions_override="Never draft."),
            first_run_charged=True,
        )

        assert tried.cases[0].new_passed is False
        assert tried.cases[0].gate_passed is False

    async def test_a_try_on_an_unpublished_agent_is_refused(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = _agent(current_version_id=None)
        service.registry.get = AsyncMock(return_value=agent)
        monkeypatch.setattr(
            failure_learning_repo, "get_cases_by_ids", AsyncMock(return_value=[_case_row(agent.id)])
        )
        with pytest.raises(BadRequestError):
            await service.start_try(
                _ctx(),
                agent.id,
                EvalTryCreate(case_ids=[uuid4()], instructions_override="New text."),
            )

    async def test_a_try_on_a_missing_case_is_not_found(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        monkeypatch.setattr(failure_learning_repo, "get_cases_by_ids", AsyncMock(return_value=[]))
        with pytest.raises(NotFoundError):
            await service.start_try(
                _ctx(),
                uuid4(),
                EvalTryCreate(case_ids=[uuid4()], instructions_override="New text."),
            )

    async def test_a_try_runs_old_and_new_and_records_both(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent, case = self._setup_try(service, monkeypatch)
        old_run, new_run = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
        service.runner.execute = AsyncMock(
            side_effect=[("old answer", old_run), ("new answer", new_run)]
        )
        monkeypatch.setattr(
            failure_learning_repo, "create_run", AsyncMock(side_effect=_created_run)
        )
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(
                side_effect=[
                    SimpleNamespace(id=old_run.id, status="failed"),
                    SimpleNamespace(id=new_run.id, status="completed"),
                ]
            ),
        )
        monkeypatch.setattr(
            conversation_repo, "last_answer_of_run", AsyncMock(return_value="Here is the refund.")
        )

        tried = await service.start_try(
            _ctx(),
            agent.id,
            EvalTryCreate(case_ids=[case.id], instructions_override="Never draft."),
            first_run_charged=True,
        )

        assert tried.passed == 1
        assert tried.gate_passed is True
        result = tried.cases[0]
        assert result.old_passed is False
        assert result.new_passed is True
        calls = service.runner.execute.await_args_list
        assert calls[0].kwargs["instructions_override"] is None
        assert calls[1].kwargs["instructions_override"] == "Never draft."
        assert all(call.kwargs["test"] is True for call in calls)

    async def test_a_failed_run_cannot_pass_by_crashing(self, monkeypatch, mock_db_session):
        """A `not_contains` expectation must not pass on a run that never answered."""
        service = _service(mock_db_session)
        agent, case = self._setup_try(service, monkeypatch)
        old_run, new_run = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
        service.runner.execute = AsyncMock(
            side_effect=[("old answer", old_run), ("new answer", new_run)]
        )
        monkeypatch.setattr(
            failure_learning_repo, "create_run", AsyncMock(side_effect=_created_run)
        )
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(
                side_effect=[
                    SimpleNamespace(id=old_run.id, status="failed"),
                    SimpleNamespace(id=new_run.id, status="failed"),
                ]
            ),
        )

        tried = await service.start_try(
            _ctx(),
            agent.id,
            EvalTryCreate(case_ids=[case.id], instructions_override="Never draft."),
            first_run_charged=True,
        )

        assert tried.failed == 1
        assert tried.cases[0].new_passed is False

    async def test_a_try_whose_old_side_passes_does_not_reproduce(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent, case = self._setup_try(service, monkeypatch)
        old_run, new_run = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
        service.runner.execute = AsyncMock(
            side_effect=[("old answer", old_run), ("new answer", new_run)]
        )
        monkeypatch.setattr(
            failure_learning_repo, "create_run", AsyncMock(side_effect=_created_run)
        )
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(
                side_effect=[
                    SimpleNamespace(id=old_run.id, status="completed"),
                    SimpleNamespace(id=new_run.id, status="completed"),
                ]
            ),
        )
        monkeypatch.setattr(
            conversation_repo,
            "last_answer_of_run",
            AsyncMock(side_effect=["Here is the refund.", "Here is the refund."]),
        )

        tried = await service.start_try(
            _ctx(),
            agent.id,
            EvalTryCreate(case_ids=[case.id], instructions_override="Never draft."),
            first_run_charged=True,
        )

        assert tried.cases[0].old_passed is True
        assert tried.cases[0].gate_passed is False
        assert tried.cases[0].reason == "case does not reproduce - the old text already passes"

    async def test_a_run_still_going_leaves_the_case_pending(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent, case = self._setup_try(service, monkeypatch)
        old_run, new_run = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
        service.runner.execute = AsyncMock(
            side_effect=[("old answer", old_run), ("new answer", new_run)]
        )
        monkeypatch.setattr(
            failure_learning_repo, "create_run", AsyncMock(side_effect=_created_run)
        )
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(
                side_effect=[
                    SimpleNamespace(id=old_run.id, status="failed"),
                    SimpleNamespace(id=new_run.id, status="running"),
                ]
            ),
        )

        tried = await service.start_try(
            _ctx(),
            agent.id,
            EvalTryCreate(case_ids=[case.id], instructions_override="Never draft."),
            first_run_charged=True,
        )

        assert tried.pending == 1
        assert tried.gate_passed is None
        assert tried.cases[0].new_passed is None

    async def test_a_refused_run_is_recorded_and_the_rest_still_start(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent, case = self._setup_try(service, monkeypatch)
        new_run = SimpleNamespace(id=uuid4())
        service.runner.execute = AsyncMock(
            side_effect=[BadRequestError(message="Monthly budget spent"), ("new", new_run)]
        )
        monkeypatch.setattr(
            failure_learning_repo, "create_run", AsyncMock(side_effect=_created_run)
        )
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(return_value=SimpleNamespace(id=new_run.id, status="completed")),
        )
        monkeypatch.setattr(
            conversation_repo, "last_answer_of_run", AsyncMock(return_value="Here is the refund.")
        )

        tried = await service.start_try(
            _ctx(),
            agent.id,
            EvalTryCreate(case_ids=[case.id], instructions_override="Never draft."),
            first_run_charged=True,
        )

        assert tried.cases[0].old_run_ids == []
        assert tried.cases[0].reason == "Monthly budget spent"
        assert tried.cases[0].gate_passed is False

    async def test_a_rate_limited_side_is_a_refusal_not_a_crash(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent, case = self._setup_try(service, monkeypatch)
        monkeypatch.setattr(
            rate_limit_module,
            "consume",
            AsyncMock(return_value=Decision(allowed=False, retry_after_seconds=60)),
        )
        service.runner.execute = AsyncMock()
        monkeypatch.setattr(
            failure_learning_repo, "create_run", AsyncMock(side_effect=_created_run)
        )

        tried = await service.start_try(
            _ctx(),
            agent.id,
            EvalTryCreate(case_ids=[case.id], instructions_override="Never draft."),
        )

        service.runner.execute.assert_not_awaited()
        assert tried.cases[0].old_run_ids == []
        assert tried.cases[0].new_run_ids == []

    async def test_a_majority_of_samples_decides_a_side(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent, case = self._setup_try(service, monkeypatch)
        runs = [SimpleNamespace(id=uuid4()) for _ in range(6)]
        service.runner.execute = AsyncMock(side_effect=[("answer", run) for run in runs])
        monkeypatch.setattr(
            failure_learning_repo, "create_run", AsyncMock(side_effect=_created_run)
        )
        # Old: 3 samples, all failed. New: 2 pass, 1 fails.
        statuses = ["failed"] * 3 + ["completed", "completed", "failed"]
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(
                side_effect=[
                    SimpleNamespace(id=run.id, status=status) for run, status in zip(runs, statuses)
                ]
            ),
        )
        monkeypatch.setattr(
            conversation_repo,
            "last_answer_of_run",
            AsyncMock(side_effect=["Here is the refund.", "Here is the refund."]),
        )

        tried = await service.start_try(
            _ctx(),
            agent.id,
            EvalTryCreate(case_ids=[case.id], instructions_override="Never draft.", samples=3),
            first_run_charged=True,
        )

        assert tried.cases[0].old_passed is False
        assert tried.cases[0].new_passed is True
        assert tried.cases[0].gate_passed is True


class TestGetTry:
    async def test_getting_a_try_judges_it_as_its_runs_stand(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        case = _case_row(agent.id)
        old_run, new_run = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
        monkeypatch.setattr(
            failure_learning_repo,
            "get_run",
            AsyncMock(
                return_value=_created_run(
                    mock_db_session,
                    agent_id=agent.id,
                    organization_id=uuid4(),
                    cases=[
                        {
                            "eval_id": str(case.id),
                            "name": case.name,
                            "expectation": case.expectation,
                            "old_run_ids": [str(old_run.id)],
                            "new_run_ids": [str(new_run.id)],
                            "samples": 1,
                            "refused": None,
                        }
                    ],
                )
            ),
        )
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(
                side_effect=[
                    SimpleNamespace(id=old_run.id, status="failed"),
                    SimpleNamespace(id=new_run.id, status="completed"),
                ]
            ),
        )
        monkeypatch.setattr(
            conversation_repo, "last_answer_of_run", AsyncMock(return_value="Here is the refund.")
        )

        tried = await service.get_try(_ctx(), agent.id, uuid4())

        assert tried.passed == 1
        assert tried.gate_passed is True

    async def test_getting_a_missing_try_is_not_found(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        monkeypatch.setattr(failure_learning_repo, "get_run", AsyncMock(return_value=None))
        with pytest.raises(NotFoundError):
            await service.get_try(_ctx(), uuid4(), uuid4())


class TestProposals:
    async def test_creating_an_instruction_proposal_defaults_to_the_current_version(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        version = SimpleNamespace(
            id=agent.current_version_id,
            agent_id=agent.id,
            version=3,
            spec=AgentSpec(name="Support", model_profile_id=uuid4()).model_dump(mode="json"),
        )
        monkeypatch.setattr(agent_repo, "get_version", AsyncMock(return_value=version))
        created = AsyncMock(side_effect=_created_proposal)
        monkeypatch.setattr(failure_learning_repo, "create_proposal", created)

        proposal = await service.create_proposal(
            _ctx(),
            agent.id,
            ProposalCreate(
                target=ProposalTarget(type="instructions"),
                old_text="Draft a PR.",
                new_text="Never draft a PR.",
                rationale="The agent drafts when told to publish.",
            ),
        )

        assert proposal.status == "draft"
        assert proposal.base_agent_version_id == agent.current_version_id
        assert proposal.base_content_sha256 is None
        assert proposal.eval_gated is True

    async def test_creating_a_proposal_against_a_named_version_checks_it(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        base_id = uuid4()
        version = SimpleNamespace(
            id=base_id,
            agent_id=agent.id,
            version=2,
            spec=AgentSpec(name="Support", model_profile_id=uuid4()).model_dump(mode="json"),
        )
        monkeypatch.setattr(agent_repo, "get_version", AsyncMock(return_value=version))
        monkeypatch.setattr(
            failure_learning_repo, "create_proposal", AsyncMock(side_effect=_created_proposal)
        )

        proposal = await service.create_proposal(
            _ctx(),
            agent.id,
            ProposalCreate(
                target=ProposalTarget(type="instructions"),
                old_text="Draft a PR.",
                new_text="Never draft a PR.",
                rationale="The agent drafts when told to publish.",
                base_agent_version_id=base_id,
            ),
        )

        assert proposal.base_agent_version_id == base_id

    async def test_creating_a_proposal_against_another_agents_version_is_not_found(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        version = SimpleNamespace(
            id=uuid4(),
            agent_id=uuid4(),
            version=2,
            spec=AgentSpec(name="Other", model_profile_id=uuid4()).model_dump(mode="json"),
        )
        monkeypatch.setattr(agent_repo, "get_version", AsyncMock(return_value=version))
        with pytest.raises(NotFoundError):
            await service.create_proposal(
                _ctx(),
                agent.id,
                ProposalCreate(
                    target=ProposalTarget(type="instructions"),
                    old_text="Draft a PR.",
                    new_text="Never draft a PR.",
                    rationale="The agent drafts when told to publish.",
                    base_agent_version_id=version.id,
                ),
            )

    async def test_a_skill_proposal_without_a_skill_is_refused(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        with pytest.raises(BadRequestError):
            await service.create_proposal(
                _ctx(),
                uuid4(),
                ProposalCreate(
                    target=ProposalTarget(type="skill"),
                    old_text="Old skill.",
                    new_text="New skill.",
                    rationale="The skill misleads.",
                ),
            )

    async def test_an_instructions_proposal_naming_a_skill_is_refused(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        with pytest.raises(BadRequestError):
            await service.create_proposal(
                _ctx(),
                uuid4(),
                ProposalCreate(
                    target=ProposalTarget(type="instructions", skill_id=uuid4()),
                    old_text="Draft a PR.",
                    new_text="Never draft a PR.",
                    rationale="The agent drafts when told to publish.",
                ),
            )

    async def test_creating_a_skill_proposal_hashes_the_current_content(
        self, monkeypatch, mock_db_session
    ):
        import hashlib

        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        skill_id = uuid4()
        skill = SimpleNamespace(id=skill_id, content="Old skill text.")
        service.skills.get = AsyncMock(return_value=skill)
        created = AsyncMock(side_effect=_created_proposal)
        monkeypatch.setattr(failure_learning_repo, "create_proposal", created)

        proposal = await service.create_proposal(
            _ctx(),
            agent.id,
            ProposalCreate(
                target=ProposalTarget(type="skill", skill_id=skill_id),
                old_text="Old skill text.",
                new_text="New skill text.",
                rationale="The skill misleads.",
            ),
        )

        assert proposal.base_agent_version_id is None
        assert proposal.base_content_sha256 == hashlib.sha256(b"Old skill text.").hexdigest()
        assert proposal.eval_gated is True

    async def test_creating_a_proposal_for_a_missing_entry_is_not_found(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        monkeypatch.setattr(failure_learning_repo, "get_entry", AsyncMock(return_value=None))
        with pytest.raises(NotFoundError):
            await service.create_proposal(
                _ctx(),
                uuid4(),
                ProposalCreate(
                    ledger_entry_id=uuid4(),
                    target=ProposalTarget(type="instructions"),
                    old_text="Draft a PR.",
                    new_text="Never draft a PR.",
                    rationale="The agent drafts when told to publish.",
                ),
            )

    async def test_creating_a_proposal_for_a_missing_try_is_not_found(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        monkeypatch.setattr(failure_learning_repo, "get_run", AsyncMock(return_value=None))
        with pytest.raises(NotFoundError):
            await service.create_proposal(
                _ctx(),
                uuid4(),
                ProposalCreate(
                    eval_try_id=uuid4(),
                    target=ProposalTarget(type="instructions"),
                    old_text="Draft a PR.",
                    new_text="Never draft a PR.",
                    rationale="The agent drafts when told to publish.",
                ),
            )

    async def test_listing_proposals(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        monkeypatch.setattr(
            failure_learning_repo,
            "list_proposals",
            AsyncMock(return_value=[_proposal_row(agent.id)]),
        )

        listed = await service.list_proposals(_ctx(), agent.id)

        assert listed.total == 1
        assert listed.items[0].eval_evidence is None
        assert listed.items[0].applied_version is None

    async def test_getting_a_proposal_judges_its_linked_try(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        case = _case_row(agent.id)
        proposal = _proposal_row(agent.id, eval_try_id=uuid4())
        old_run, new_run = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        monkeypatch.setattr(
            failure_learning_repo,
            "get_run",
            AsyncMock(
                return_value=_created_run(
                    mock_db_session,
                    agent_id=agent.id,
                    organization_id=uuid4(),
                    cases=[
                        {
                            "eval_id": str(case.id),
                            "name": case.name,
                            "expectation": case.expectation,
                            "old_run_ids": [str(old_run.id)],
                            "new_run_ids": [str(new_run.id)],
                            "samples": 1,
                            "refused": None,
                        }
                    ],
                )
            ),
        )
        monkeypatch.setattr(
            agent_run_repo,
            "get_run",
            AsyncMock(
                side_effect=[
                    SimpleNamespace(id=old_run.id, status="failed"),
                    SimpleNamespace(id=new_run.id, status="completed"),
                ]
            ),
        )
        monkeypatch.setattr(
            conversation_repo, "last_answer_of_run", AsyncMock(return_value="Here is the refund.")
        )

        read = await service.get_proposal(_ctx(), agent.id, proposal.id)

        assert read.eval_evidence is not None
        assert read.eval_evidence.gate_passed is True
        assert read.eval_gated is True

    async def test_getting_a_missing_proposal_is_not_found(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=None))
        with pytest.raises(NotFoundError):
            await service.get_proposal(_ctx(), uuid4(), uuid4())

    async def test_rejecting_a_proposal_audits_the_reason(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        proposal = _proposal_row(agent.id)
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        monkeypatch.setattr(
            failure_learning_repo,
            "update_proposal",
            AsyncMock(return_value=_proposal_row(agent.id, status="rejected")),
        )
        audited = AsyncMock()
        monkeypatch.setattr("app.services.failure_learning.record_audit", audited)

        rejected = await service.reject_proposal(
            _ctx(), agent.id, proposal.id, ProposalReject(reason="The rule is too broad.")
        )

        assert rejected.status == "rejected"
        audited.assert_awaited_once()
        call = audited.await_args
        assert call.kwargs["action"] == "agent.instruction_proposal_rejected"
        assert call.kwargs["details"]["reason"] == "The rule is too broad."

    async def test_rejecting_a_decided_proposal_is_a_conflict(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        proposal = _proposal_row(agent.id, status="applied")
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        with pytest.raises(ConflictError):
            await service.reject_proposal(
                _ctx(), agent.id, proposal.id, ProposalReject(reason="Too late.")
            )


def _created_proposal(_db, **fields):
    """A proposal row holding the fields the service created, as the repository would."""
    return SimpleNamespace(
        id=uuid4(),
        organization_id=fields["organization_id"],
        agent_id=fields["agent_id"],
        ledger_entry_id=fields.get("ledger_entry_id"),
        eval_try_id=fields.get("eval_try_id"),
        target_type=fields["target_type"],
        skill_id=fields.get("skill_id"),
        old_text=fields["old_text"],
        new_text=fields["new_text"],
        rationale=fields["rationale"],
        base_agent_version_id=fields.get("base_agent_version_id"),
        base_content_sha256=fields.get("base_content_sha256"),
        prior_skill_content=fields.get("prior_skill_content"),
        applied_content_sha256=fields.get("applied_content_sha256"),
        reverted_by_user_id=fields.get("reverted_by_user_id"),
        reverted_at=fields.get("reverted_at"),
        status=fields["status"],
        applied_version_id=None,
        created_by_user_id=fields.get("created_by_user_id"),
        decided_by_user_id=None,
        decided_at=None,
        created_at=_NOW,
        updated_at=None,
    )


class TestApply:
    def _setup_apply(self, service, monkeypatch, *, proposal=None, agent=None):
        """An agent whose draft is exactly its published spec, and a proposal for it."""
        spec = AgentSpec(name="Support", model_profile_id=uuid4()).model_dump(mode="json")
        agent = agent or _agent(draft_spec=spec)
        service.registry.get = AsyncMock(return_value=agent)
        proposal = proposal or _proposal_row(
            agent.id,
            base_agent_version_id=agent.current_version_id,
            eval_try_id=uuid4(),
        )
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        published = SimpleNamespace(
            id=agent.current_version_id, agent_id=agent.id, version=3, spec=spec
        )
        applied = SimpleNamespace(id=uuid4(), agent_id=agent.id, version=4, spec=spec)

        async def _get_version(_db, version_id, *, organization_id):
            return applied if version_id == applied.id else published

        monkeypatch.setattr(agent_repo, "get_version", _get_version)
        service.registry.save_draft = AsyncMock(return_value=agent)
        service.registry.publish = AsyncMock(return_value=applied)
        monkeypatch.setattr(
            failure_learning_repo,
            "update_proposal",
            AsyncMock(
                side_effect=lambda _db, *, proposal, update_data: _proposal_row(
                    proposal.agent_id,
                    id=proposal.id,
                    ledger_entry_id=proposal.ledger_entry_id,
                    eval_try_id=proposal.eval_try_id,
                    target_type=proposal.target_type,
                    skill_id=proposal.skill_id,
                    old_text=proposal.old_text,
                    new_text=proposal.new_text,
                    rationale=proposal.rationale,
                    base_agent_version_id=proposal.base_agent_version_id,
                    base_content_sha256=proposal.base_content_sha256,
                    status=update_data["status"],
                    applied_version_id=update_data["applied_version_id"],
                )
            ),
        )
        monkeypatch.setattr(failure_learning_repo, "get_entry", AsyncMock(return_value=None))
        audited = AsyncMock()
        monkeypatch.setattr("app.services.failure_learning.record_audit", audited)
        return agent, proposal, applied, audited

    def _gate_try(
        self,
        monkeypatch,
        agent_id,
        *,
        passed=True,
        pending=False,
        proposal_id=None,
        target_skill_id=None,
        tested_content_sha256=None,
        proposal=None,
    ):
        """A linked try whose verdict is a pass, a fail, or still going."""
        if proposal is not None:
            proposal_id = proposal.id
            tested_content_sha256 = hashlib.sha256(proposal.new_text.encode("utf-8")).hexdigest()
        case = _case_row(agent_id)
        old_run, new_run = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
        monkeypatch.setattr(
            failure_learning_repo,
            "get_run",
            AsyncMock(
                return_value=_created_run(
                    None,
                    agent_id=agent_id,
                    organization_id=uuid4(),
                    proposal_id=proposal_id,
                    target_skill_id=target_skill_id,
                    tested_content_sha256=tested_content_sha256,
                    cases=[
                        {
                            "eval_id": str(case.id),
                            "name": case.name,
                            "expectation": case.expectation,
                            "old_run_ids": [str(old_run.id)],
                            "new_run_ids": [str(new_run.id)],
                            "samples": 1,
                            "refused": None,
                        }
                    ],
                )
            ),
        )
        new_status = "running" if pending else "completed"
        old_status = "failed" if passed or pending else "completed"
        runs = {
            old_run.id: SimpleNamespace(id=old_run.id, status=old_status),
            new_run.id: SimpleNamespace(id=new_run.id, status=new_status),
        }

        async def _get_run(_db, run_id, *, organization_id):
            return runs.get(run_id)

        monkeypatch.setattr(agent_run_repo, "get_run", _get_run)
        monkeypatch.setattr(
            conversation_repo, "last_answer_of_run", AsyncMock(return_value="Here is the refund.")
        )

    async def test_applying_an_instruction_proposal_publishes_the_new_text(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent, proposal, applied, audited = self._setup_apply(service, monkeypatch)
        self._gate_try(monkeypatch, agent.id, proposal=proposal)

        read = await service.apply_proposal(_ctx(), agent.id, proposal.id)

        assert read.status == "applied"
        assert read.applied_version is not None
        assert read.applied_version.number == 4
        saved = service.registry.save_draft.await_args.args[2]
        assert saved.instructions == "Never draft a PR."
        publish = service.registry.publish.await_args
        assert publish.args[1] == agent.id
        assert str(proposal.id) in publish.kwargs["note"]
        audited.assert_awaited_once()
        call = audited.await_args
        assert call.kwargs["action"] == "agent.instruction_proposal_applied"
        assert call.kwargs["target_type"] == "agent"
        assert call.kwargs["target_id"] == str(agent.id)
        assert call.kwargs["details"]["version_id"] == str(applied.id)
        assert call.kwargs["details"]["eval_try_id"] == str(proposal.eval_try_id)

    async def test_applying_a_decided_proposal_is_a_conflict(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent, proposal, _, _ = self._setup_apply(
            service, monkeypatch, proposal=_proposal_row(uuid4(), status="applied")
        )
        with pytest.raises(ConflictError):
            await service.apply_proposal(_ctx(), agent.id, proposal.id)
        service.registry.publish.assert_not_awaited()

    async def test_applying_without_a_try_is_refused(self, monkeypatch, mock_db_session):
        """No linked try means no evidence: the gate cannot have passed."""
        service = _service(mock_db_session)
        agent, proposal, _, _ = self._setup_apply(
            service,
            monkeypatch,
            proposal=_proposal_row(uuid4(), eval_try_id=None),
        )
        with pytest.raises(BadRequestError, match="names no eval try"):
            await service.apply_proposal(_ctx(), agent.id, proposal.id)
        service.registry.publish.assert_not_awaited()

    async def test_applying_with_a_failed_try_is_refused(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent, proposal, _, _ = self._setup_apply(service, monkeypatch)
        self._gate_try(monkeypatch, agent.id, passed=False, proposal=proposal)

        with pytest.raises(BadRequestError, match="has not passed the eval gate"):
            await service.apply_proposal(_ctx(), agent.id, proposal.id)
        service.registry.publish.assert_not_awaited()

    async def test_a_passing_try_on_different_instruction_text_does_not_clear_the_gate(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent, proposal, _, _ = self._setup_apply(service, monkeypatch)
        self._gate_try(
            monkeypatch,
            agent.id,
            proposal_id=proposal.id,
            tested_content_sha256=hashlib.sha256(b"Different passing text.").hexdigest(),
        )

        with pytest.raises(ConflictError, match="did not test this exact proposal"):
            await service.apply_proposal(_ctx(), agent.id, proposal.id)
        service.registry.publish.assert_not_awaited()

    async def test_applying_with_a_pending_try_is_refused(self, monkeypatch, mock_db_session):
        """A run still going is not evidence the new text works."""
        service = _service(mock_db_session)
        agent, proposal, _, _ = self._setup_apply(service, monkeypatch)
        self._gate_try(monkeypatch, agent.id, pending=True, proposal=proposal)

        with pytest.raises(BadRequestError, match="has not passed the eval gate"):
            await service.apply_proposal(_ctx(), agent.id, proposal.id)
        service.registry.publish.assert_not_awaited()

    async def test_applying_after_a_republish_is_a_conflict(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent, proposal, _, _ = self._setup_apply(service, monkeypatch)
        proposal = _proposal_row(
            agent.id,
            base_agent_version_id=uuid4(),
            eval_try_id=proposal.eval_try_id,
        )
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        self._gate_try(monkeypatch, agent.id, proposal=proposal)

        with pytest.raises(ConflictError, match="republished"):
            await service.apply_proposal(_ctx(), agent.id, proposal.id)
        service.registry.publish.assert_not_awaited()

    async def test_applying_with_unpublished_draft_edits_is_a_conflict(
        self, monkeypatch, mock_db_session
    ):
        """A builder's in-progress edits must not be overwritten by save_draft."""
        service = _service(mock_db_session)
        agent, proposal, _, _ = self._setup_apply(service, monkeypatch)
        edited = AgentSpec(name="Support", model_profile_id=uuid4()).model_dump(mode="json")
        edited["instructions"] = "Something else entirely."
        agent.draft_spec = edited
        self._gate_try(monkeypatch, agent.id, proposal=proposal)

        with pytest.raises(ConflictError, match="unpublished draft edits"):
            await service.apply_proposal(_ctx(), agent.id, proposal.id)
        service.registry.publish.assert_not_awaited()

    async def test_applying_resolves_the_linked_ledger_entry(self, monkeypatch, mock_db_session):
        service = _service(mock_db_session)
        agent, proposal, _, _ = self._setup_apply(service, monkeypatch)
        entry_id = uuid4()
        proposal = _proposal_row(
            agent.id,
            ledger_entry_id=entry_id,
            base_agent_version_id=agent.current_version_id,
            eval_try_id=proposal.eval_try_id,
        )
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        monkeypatch.setattr(
            failure_learning_repo,
            "get_entry",
            AsyncMock(return_value=_entry_row(agent.id, id=entry_id, status="open")),
        )
        updated_entry = AsyncMock()
        monkeypatch.setattr(failure_learning_repo, "update_entry", updated_entry)
        self._gate_try(monkeypatch, agent.id, proposal=proposal)

        await service.apply_proposal(_ctx(), agent.id, proposal.id)

        updated_entry.assert_awaited_once()
        assert updated_entry.await_args.kwargs["update_data"]["status"] == "resolved"
        assert updated_entry.await_args.kwargs["update_data"]["resolved_proposal_id"] == proposal.id

    async def test_applying_a_skill_proposal_edits_the_skill_live(
        self, monkeypatch, mock_db_session
    ):
        import hashlib

        service = _service(mock_db_session)
        agent = _agent()
        service.registry.get = AsyncMock(return_value=agent)
        skill_id = uuid4()
        skill = SimpleNamespace(id=skill_id, content="Old skill text.")
        proposal = _proposal_row(
            agent.id,
            target_type="skill",
            skill_id=skill_id,
            eval_try_id=uuid4(),
            old_text="Old skill text.",
            new_text="New skill text.",
            base_agent_version_id=None,
            base_content_sha256=hashlib.sha256(b"Old skill text.").hexdigest(),
        )
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        service.skills.get = AsyncMock(return_value=skill)
        updated_skill = AsyncMock()
        service.skills.update = updated_skill
        self._gate_try(
            monkeypatch,
            agent.id,
            proposal_id=proposal.id,
            target_skill_id=skill_id,
            tested_content_sha256=hashlib.sha256(b"New skill text.").hexdigest(),
        )
        monkeypatch.setattr(
            failure_learning_repo,
            "update_proposal",
            AsyncMock(
                side_effect=lambda _db, *, proposal, update_data: _proposal_row(
                    proposal.agent_id,
                    id=proposal.id,
                    target_type="skill",
                    skill_id=skill_id,
                    old_text=proposal.old_text,
                    new_text=proposal.new_text,
                    rationale=proposal.rationale,
                    base_content_sha256=proposal.base_content_sha256,
                    prior_skill_content=update_data.get("prior_skill_content"),
                    applied_content_sha256=update_data.get("applied_content_sha256"),
                    status=update_data["status"],
                    applied_version_id=None,
                )
            ),
        )
        monkeypatch.setattr(failure_learning_repo, "get_entry", AsyncMock(return_value=None))
        audited = AsyncMock()
        monkeypatch.setattr("app.services.failure_learning.record_audit", audited)

        read = await service.apply_proposal(_ctx(), agent.id, proposal.id)

        assert read.status == "applied"
        assert read.applied_version is None
        assert read.eval_gated is True
        assert read.rollback_available is True
        assert read.applied_content_sha256 == hashlib.sha256(b"New skill text.").hexdigest()
        assert service.skills.update.await_args.args[2].content == "New skill text."
        update_data = failure_learning_repo.update_proposal.await_args.kwargs["update_data"]
        assert update_data["prior_skill_content"] == "Old skill text."
        updated_skill.assert_awaited_once()
        assert updated_skill.await_args.args[2].content == "New skill text."
        audited.assert_awaited_once()
        call = audited.await_args
        assert call.kwargs["target_type"] == "skill"
        assert call.kwargs["target_id"] == str(skill_id)
        assert (
            call.kwargs["details"]["content_sha256"]
            == hashlib.sha256(b"New skill text.").hexdigest()
        )

    async def test_applying_a_skill_proposal_after_a_skill_edit_is_a_conflict(
        self, monkeypatch, mock_db_session
    ):
        import hashlib

        service = _service(mock_db_session)
        agent = _agent()
        service.registry.get = AsyncMock(return_value=agent)
        skill_id = uuid4()
        skill = SimpleNamespace(id=skill_id, content="Somebody else edited this.")
        proposal = _proposal_row(
            agent.id,
            target_type="skill",
            skill_id=skill_id,
            base_content_sha256=hashlib.sha256(b"Old skill text.").hexdigest(),
        )
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        service.skills.get = AsyncMock(return_value=skill)
        updated_skill = AsyncMock()
        service.skills.update = updated_skill

        with pytest.raises(ConflictError, match="has changed since"):
            await service.apply_proposal(_ctx(), agent.id, proposal.id)
        updated_skill.assert_not_awaited()

    async def test_applying_a_skill_proposal_without_an_eval_try_is_refused(
        self, monkeypatch, mock_db_session
    ):
        import hashlib

        service = _service(mock_db_session)
        agent = _agent()
        service.registry.get = AsyncMock(return_value=agent)
        skill_id = uuid4()
        skill = SimpleNamespace(id=skill_id, content="Old skill text.")
        proposal = _proposal_row(
            agent.id,
            target_type="skill",
            skill_id=skill_id,
            base_content_sha256=hashlib.sha256(b"Old skill text.").hexdigest(),
        )
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        service.skills.get = AsyncMock(return_value=skill)
        updated_skill = AsyncMock()
        service.skills.update = updated_skill

        with pytest.raises(BadRequestError, match="names no eval try"):
            await service.apply_proposal(_ctx(), agent.id, proposal.id)

        updated_skill.assert_not_awaited()

    async def test_reverting_a_skill_proposal_restores_its_snapshot(
        self, monkeypatch, mock_db_session
    ):
        import hashlib

        service = _service(mock_db_session)
        agent = _agent()
        service.registry.get = AsyncMock(return_value=agent)
        skill_id = uuid4()
        proposal = _proposal_row(
            agent.id,
            target_type="skill",
            skill_id=skill_id,
            status="applied",
            prior_skill_content="Old skill text.",
            applied_content_sha256=hashlib.sha256(b"New skill text.").hexdigest(),
        )
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        service.skills.get = AsyncMock(
            return_value=SimpleNamespace(id=skill_id, content="New skill text.")
        )
        restored = AsyncMock()
        service.skills.update = restored
        monkeypatch.setattr(
            failure_learning_repo,
            "update_proposal",
            AsyncMock(
                side_effect=lambda _db, *, proposal, update_data: _proposal_row(
                    agent.id,
                    id=proposal.id,
                    target_type="skill",
                    skill_id=skill_id,
                    status="applied",
                    prior_skill_content=proposal.prior_skill_content,
                    applied_content_sha256=proposal.applied_content_sha256,
                    reverted_at=update_data["reverted_at"],
                    reverted_by_user_id=update_data["reverted_by_user_id"],
                )
            ),
        )
        monkeypatch.setattr("app.services.failure_learning.record_audit", AsyncMock())

        read = await service.revert_proposal(_ctx(), agent.id, proposal.id)

        assert read.status == "applied"
        assert read.reverted_at is not None
        assert read.rollback_available is False
        restored.assert_awaited_once()
        assert restored.await_args.args[2].content == "Old skill text."


class TestEvidenceAndRestoreBoundaries:
    @pytest.mark.parametrize(
        ("counts", "sample_counts"),
        [((3, 3), (3, 3)), ((3, 2), (1, 5))],
    )
    async def test_model_evidence_is_bounded_and_does_not_reload_existing_samples(
        self, monkeypatch, mock_db_session, counts, sample_counts
    ):
        service = _service(mock_db_session)
        agents = [uuid4(), uuid4()]
        samples = {
            agent_id: [uuid4() for _ in range(size)]
            for agent_id, size in zip(agents, sample_counts)
        }
        sampled = []

        async def read_samples(_db, *, agent_id, **_kwargs):
            sampled.append(agent_id)
            return samples[agent_id]

        monkeypatch.setattr(
            agent_run_repo,
            "failure_groups",
            AsyncMock(
                return_value=[
                    _group(agent_id, count=count) for agent_id, count in zip(agents, counts)
                ]
            ),
        )
        monkeypatch.setattr(agent_run_repo, "failure_group_samples", read_samples)
        monkeypatch.setattr(agent_run_repo, "stalled_runs", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_run_repo, "down_rated_messages", AsyncMock(return_value=[]))
        monkeypatch.setattr(failure_learning_repo, "open_entries", AsyncMock(return_value=[]))
        monkeypatch.setattr(agent_repo, "list_by_ids", AsyncMock(return_value=([], 0)))

        patterns = await service.list_org_patterns(_ctx())

        [model] = [pattern for pattern in patterns.items if pattern.agent_id is None]
        assert model.count == sum(counts)
        assert model.sample_run_ids == (samples[agents[0]] + samples[agents[1]])[:5]
        assert sampled == agents

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("overrides", "current_content", "message"),
        [
            ({"target_type": "instructions"}, "Applied procedure", "no available"),
            ({"status": "draft"}, "Applied procedure", "no available"),
            ({"reverted_at": _NOW}, "Applied procedure", "no available"),
            ({"prior_skill_content": None}, "Applied procedure", "no available"),
            ({"skill_id": None}, "Applied procedure", "no complete"),
            ({"applied_content_sha256": None}, "Applied procedure", "no complete"),
            ({}, "A later operator edit", "refusing to overwrite"),
        ],
    )
    async def test_rollback_refuses_unavailable_or_stale_evidence_before_any_write(
        self, monkeypatch, mock_db_session, overrides, current_content, message
    ):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        fields = {
            "target_type": "skill",
            "skill_id": uuid4(),
            "status": "applied",
            "prior_skill_content": "Original procedure",
            "applied_content_sha256": hashlib.sha256(b"Applied procedure").hexdigest(),
        }
        fields.update(overrides)
        proposal = _proposal_row(agent.id, **fields)
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        service.skills.get = AsyncMock(
            return_value=SimpleNamespace(id=proposal.skill_id, content=current_content)
        )
        service.skills.update = AsyncMock()
        record = AsyncMock()
        audit = AsyncMock()
        monkeypatch.setattr(failure_learning_repo, "update_proposal", record)
        monkeypatch.setattr("app.services.failure_learning.record_audit", audit)

        with pytest.raises(ConflictError, match=message):
            await service.revert_proposal(_ctx(), agent.id, proposal.id)

        service.skills.update.assert_not_awaited()
        record.assert_not_awaited()
        audit.assert_not_awaited()
        if overrides:
            service.skills.get.assert_not_awaited()

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("mode", "exception", "message"),
        [
            ("missing", BadRequestError, "must name its skill"),
            ("changed", ConflictError, "has changed since"),
            ("unattached", BadRequestError, "attached to the published agent"),
        ],
    )
    async def test_a_skill_try_refuses_missing_stale_or_unbound_content_before_running(
        self, monkeypatch, mock_db_session, mode, exception, message
    ):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        case = _case_row(agent.id)
        proposal = _proposal_row(
            agent.id,
            target_type="skill",
            skill_id=None if mode == "missing" else uuid4(),
            base_content_sha256=hashlib.sha256(b"Original procedure").hexdigest(),
        )
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        monkeypatch.setattr(
            failure_learning_repo, "get_cases_by_ids", AsyncMock(return_value=[case])
        )
        monkeypatch.setattr(
            agent_repo,
            "get_version",
            AsyncMock(
                return_value=SimpleNamespace(
                    spec=AgentSpec(name="Support", model_profile_id=uuid4()).model_dump(mode="json")
                )
            ),
        )
        service.skills.get = AsyncMock(
            return_value=SimpleNamespace(
                id=proposal.skill_id,
                content="Later edit" if mode == "changed" else "Original procedure",
            )
        )
        service.runner.execute = AsyncMock()
        service.conversations.create_conversation = AsyncMock()
        written = AsyncMock()
        monkeypatch.setattr(failure_learning_repo, "create_run", written)

        with pytest.raises(exception, match=message):
            await service.start_try(
                _ctx(), agent.id, EvalTryCreate(case_ids=[case.id], proposal_id=proposal.id)
            )

        service.runner.execute.assert_not_awaited()
        service.conversations.create_conversation.assert_not_awaited()
        written.assert_not_awaited()

    async def test_a_missing_linked_try_is_reported_without_inventing_evidence(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        proposal = _proposal_row(agent.id, eval_try_id=uuid4())
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        monkeypatch.setattr(failure_learning_repo, "get_run", AsyncMock(return_value=None))

        read = await service.get_proposal(_ctx(), agent.id, proposal.id)

        assert read.eval_try_id == proposal.eval_try_id
        assert read.eval_evidence is None
        assert read.status == "draft"


class TestProposalBranches:
    """The refusal branches the happy paths never take."""

    async def test_creating_an_instruction_proposal_for_an_unpublished_agent_has_no_base(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent = _agent(current_version_id=None)
        service.registry.get = AsyncMock(return_value=agent)
        monkeypatch.setattr(
            failure_learning_repo, "create_proposal", AsyncMock(side_effect=_created_proposal)
        )

        proposal = await service.create_proposal(
            _ctx(),
            agent.id,
            ProposalCreate(
                target=ProposalTarget(type="instructions"),
                old_text="Draft a PR.",
                new_text="Never draft a PR.",
                rationale="The agent drafts when told to publish.",
            ),
        )

        assert proposal.base_agent_version_id is None

    async def test_creating_a_proposal_against_a_missing_version_is_not_found(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        monkeypatch.setattr(agent_repo, "get_version", AsyncMock(return_value=None))
        with pytest.raises(NotFoundError):
            await service.create_proposal(
                _ctx(),
                uuid4(),
                ProposalCreate(
                    target=ProposalTarget(type="instructions"),
                    old_text="Draft a PR.",
                    new_text="Never draft a PR.",
                    rationale="The agent drafts when told to publish.",
                    base_agent_version_id=uuid4(),
                ),
            )

    async def test_creating_a_proposal_with_a_linked_try_keeps_the_link(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        try_id = uuid4()
        version = SimpleNamespace(
            id=agent.current_version_id,
            agent_id=agent.id,
            version=3,
            spec=AgentSpec(name="Support", model_profile_id=uuid4()).model_dump(mode="json"),
        )
        monkeypatch.setattr(agent_repo, "get_version", AsyncMock(return_value=version))
        monkeypatch.setattr(
            failure_learning_repo,
            "get_run",
            AsyncMock(
                return_value=_created_run(
                    None, agent_id=agent.id, organization_id=uuid4(), cases=[]
                )
            ),
        )
        monkeypatch.setattr(
            failure_learning_repo, "create_proposal", AsyncMock(side_effect=_created_proposal)
        )

        proposal = await service.create_proposal(
            _ctx(),
            agent.id,
            ProposalCreate(
                eval_try_id=try_id,
                target=ProposalTarget(type="instructions"),
                old_text="Draft a PR.",
                new_text="Never draft a PR.",
                rationale="The agent drafts when told to publish.",
            ),
        )

        assert proposal.eval_try_id == try_id

    async def test_getting_an_applied_proposal_whose_version_is_gone_reports_no_version(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent = service.registry.get.return_value
        proposal = _proposal_row(agent.id, status="applied", applied_version_id=uuid4())
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        monkeypatch.setattr(agent_repo, "get_version", AsyncMock(return_value=None))

        read = await service.get_proposal(_ctx(), agent.id, proposal.id)

        assert read.status == "applied"
        assert read.applied_version is None


class TestApplyBranches:
    """The apply refusals the happy paths never take."""

    async def test_applying_an_unpublished_agent_is_refused(self, monkeypatch, mock_db_session):
        """A gate-passed try implies a publish, so no published version means
        the agent row changed underneath - refuse rather than publish blind."""
        service = _service(mock_db_session)
        agent = _agent(current_version_id=None)
        service.registry.get = AsyncMock(return_value=agent)
        proposal = _proposal_row(agent.id, base_agent_version_id=None, eval_try_id=uuid4())
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        monkeypatch.setattr(
            failure_learning_repo,
            "get_run",
            AsyncMock(
                return_value=_created_run(
                    None, agent_id=agent.id, organization_id=uuid4(), cases=[]
                )
            ),
        )
        TestApply()._gate_try(monkeypatch, agent.id, proposal=proposal)

        with pytest.raises(BadRequestError, match="has not been published yet"):
            await service.apply_proposal(_ctx(), agent.id, proposal.id)

    async def test_applying_when_the_published_version_is_missing_is_refused(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent, proposal, _, _ = TestApply()._setup_apply(service, monkeypatch)
        monkeypatch.setattr(agent_repo, "get_version", AsyncMock(return_value=None))
        TestApply()._gate_try(monkeypatch, agent.id, proposal=proposal)

        with pytest.raises(BadRequestError, match="missing version"):
            await service.apply_proposal(_ctx(), agent.id, proposal.id)
        service.registry.publish.assert_not_awaited()

    async def test_applying_a_skill_proposal_without_a_skill_is_refused(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent = _agent()
        service.registry.get = AsyncMock(return_value=agent)
        proposal = _proposal_row(agent.id, target_type="skill", skill_id=None)
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        with pytest.raises(BadRequestError, match="names its skill"):
            await service.apply_proposal(_ctx(), agent.id, proposal.id)

    async def test_applying_a_skill_proposal_without_a_base_hash_is_a_conflict(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent = _agent()
        service.registry.get = AsyncMock(return_value=agent)
        skill_id = uuid4()
        proposal = _proposal_row(
            agent.id, target_type="skill", skill_id=skill_id, base_content_sha256=None
        )
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        service.skills.get = AsyncMock(
            return_value=SimpleNamespace(id=skill_id, content="Old skill text.")
        )

        with pytest.raises(ConflictError, match="no base content hash"):
            await service.apply_proposal(_ctx(), agent.id, proposal.id)

    async def test_applying_leaves_an_already_resolved_entry_alone(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent, proposal, _, _ = TestApply()._setup_apply(service, monkeypatch)
        entry_id = uuid4()
        proposal = _proposal_row(
            agent.id,
            ledger_entry_id=entry_id,
            base_agent_version_id=agent.current_version_id,
            eval_try_id=proposal.eval_try_id,
        )
        monkeypatch.setattr(failure_learning_repo, "get_proposal", AsyncMock(return_value=proposal))
        monkeypatch.setattr(
            failure_learning_repo,
            "get_entry",
            AsyncMock(
                return_value=_entry_row(
                    agent.id, id=entry_id, status="resolved", resolved_proposal_id=uuid4()
                )
            ),
        )
        updated_entry = AsyncMock()
        monkeypatch.setattr(failure_learning_repo, "update_entry", updated_entry)
        TestApply()._gate_try(monkeypatch, agent.id, proposal=proposal)

        await service.apply_proposal(_ctx(), agent.id, proposal.id)

        updated_entry.assert_not_awaited()

    async def test_applying_with_a_missing_linked_try_is_refused(
        self, monkeypatch, mock_db_session
    ):
        service = _service(mock_db_session)
        agent, proposal, _, _ = TestApply()._setup_apply(service, monkeypatch)
        monkeypatch.setattr(failure_learning_repo, "get_run", AsyncMock(return_value=None))

        with pytest.raises(BadRequestError, match="linked eval try is gone"):
            await service.apply_proposal(_ctx(), agent.id, proposal.id)
        service.registry.publish.assert_not_awaited()


class TestModelReprs:
    """Each row's repr names what it is - the form logs and tracebacks show."""

    def test_reprs_name_the_row(self):
        from app.db.models.failure_learning import (
            AgentEvalCase,
            AgentEvalRun,
            AgentFailureLedger,
            AgentInstructionProposal,
        )

        agent_id = uuid4()
        assert "AgentFailureLedger" in repr(
            AgentFailureLedger(
                organization_id=uuid4(),
                agent_id=agent_id,
                scope="agent",
                pattern_key="failed:ModelHTTPError:400",
                title="400s",
                summary="Keeps failing.",
                evidence={},
                status="draft",
            )
        )
        assert "AgentEvalCase" in repr(
            AgentEvalCase(
                organization_id=uuid4(),
                agent_id=agent_id,
                name="Refund loop",
                position=1,
                input={"message": "Refund me"},
                expectation={"kind": "not_contains", "field": "text", "value": "draft"},
            )
        )
        assert "AgentEvalRun" in repr(
            AgentEvalRun(organization_id=uuid4(), agent_id=agent_id, cases=[])
        )
        assert "AgentInstructionProposal" in repr(
            AgentInstructionProposal(
                organization_id=uuid4(),
                agent_id=agent_id,
                target_type="instructions",
                old_text="Draft a PR.",
                new_text="Never draft a PR.",
                rationale="The agent drafts when told to publish.",
            )
        )
