"""Retrying a finished run: the same request, as a new run.

The original row is never mutated or re-executed. A retry reads the run's
own user turn back off its transcript, rebuilds the conversation's history
as it stood when that turn was asked, and executes the agent on it - the
new run links to the original through `retry_of_run_id`, independently of
delegation ancestry.

The refusals are the point as much as the run: a retry spends real money as
the person who started the run, so anybody else, a key, a run that has not
finished, and a run with no request to re-issue are all refused rather than
guessed at.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import RunStatus
from app.repositories.agent_run import create_run, sum_cost_since
from app.services.agent_runner import AgentRunnerService

pytestmark = pytest.mark.anyio

MODULE = "app.services.agent_runner"


@pytest.fixture(autouse=True)
def ordinary_runs_have_no_room_request():
    with patch("app.repositories.room_submission.for_run", new=AsyncMock(return_value=None)):
        yield


async def test_a_room_run_requires_a_new_explicit_queued_request():
    service = AgentRunnerService(MagicMock())
    original = _run()
    ctx = _ctx(user_id=original.user_id)
    with (
        patch(f"{MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=original)),
        patch("app.repositories.room_submission.for_run", new=AsyncMock(return_value=object())),
        patch.object(service, "execute", new=AsyncMock()) as execute,
        pytest.raises(BadRequestError, match="project room"),
    ):
        await service.retry_run(ctx, original.id)
    execute.assert_not_called()


def _ctx(*, user_id=None, api_key_id=None) -> AuthContext:
    return AuthContext(
        user_id=user_id or uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=OrgRoleName.OWNER,
        api_key_id=api_key_id,
    )


def _run(**overrides) -> SimpleNamespace:
    row = {
        "id": uuid.uuid4(),
        "agent_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "parent_run_id": None,
        "retry_of_run_id": None,
        "surface": "web",
        "status": RunStatus.FAILED.value,
        "error": "The run did not finish (ModelHTTPError, HTTP 400)",
        "cost_usd": Decimal("0.01"),
        "cost_is_partial": False,
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    row.update(overrides)
    return SimpleNamespace(**row)


def _message(*, role, content, row_id=None, files=None):
    return SimpleNamespace(id=row_id or uuid.uuid4(), role=role, content=content, files=files or [])


async def test_retry_row_stays_top_level_and_keeps_its_origin():
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    original_id = uuid.uuid4()

    retry = await create_run(
        db,
        organization_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        agent_version_id=None,
        user_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        surface="web",
        model_label=None,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        retry_of_run_id=original_id,
    )

    assert retry.retry_of_run_id == original_id
    assert retry.parent_run_id is None


class TestRetryRefusals:
    async def test_a_key_cannot_retry(self):
        """A retry spends as a person, and a key is not one - the same rule
        `cancel_parked` keeps for stopping a run."""
        service = AgentRunnerService(MagicMock())
        ctx = _ctx(api_key_id=uuid.uuid4())

        with pytest.raises(AuthorizationError, match="signed-in session"):
            await service.retry_run(ctx, uuid.uuid4())

    @pytest.mark.security
    async def test_a_run_in_another_tenant_reads_as_absent(self):
        service = AgentRunnerService(MagicMock())

        with (
            patch(f"{MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError, match="Run not found"),
        ):
            await service.retry_run(_ctx(), uuid.uuid4())

    async def test_somebody_elses_run_is_not_theirs_to_retry(self):
        service = AgentRunnerService(MagicMock())
        original = _run()
        ctx = _ctx(user_id=uuid.uuid4())

        with (
            patch(f"{MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=original)),
            pytest.raises(AuthorizationError, match="who started this run"),
        ):
            await service.retry_run(ctx, original.id)

    @pytest.mark.parametrize(
        "status",
        [RunStatus.RUNNING, RunStatus.AWAITING_APPROVAL, RunStatus.AWAITING_ANSWER],
        ids=lambda status: status.value,
    )
    async def test_a_run_that_has_not_finished_is_not_retried(self, status):
        """Running and parked runs are refused in the same words
        `cancel_parked` refuses a run that is not waiting: the retry is for
        finished runs, and a live one has a stop, a parked one a resume."""
        service = AgentRunnerService(MagicMock())
        original = _run(status=status.value)
        ctx = _ctx(user_id=original.user_id)

        with (
            patch(f"{MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=original)),
            pytest.raises(BadRequestError, match="has not finished"),
        ):
            await service.retry_run(ctx, original.id)

    async def test_a_run_with_no_conversation_has_nothing_to_retry_from(self):
        service = AgentRunnerService(MagicMock())
        original = _run(conversation_id=None)
        ctx = _ctx(user_id=original.user_id)

        with (
            patch(f"{MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=original)),
            pytest.raises(BadRequestError, match="no conversation"),
        ):
            await service.retry_run(ctx, original.id)

    async def test_a_run_with_no_user_turn_has_no_request_to_reissue(self):
        """A delegation or a workflow step: the transcript holds what the
        agent did, not a question somebody asked."""
        service = AgentRunnerService(MagicMock())
        original = _run()
        ctx = _ctx(user_id=original.user_id)

        with (
            patch(f"{MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=original)),
            patch.object(
                service,
                "get_run_transcript",
                new=AsyncMock(
                    return_value=(
                        original,
                        [_message(role="assistant", content="Working on it")],
                        1,
                    )
                ),
            ),
            pytest.raises(BadRequestError, match="no user turn"),
        ):
            await service.retry_run(ctx, original.id)

    async def test_a_deleted_conversation_is_refused_before_model_or_attachment_work(self):
        service = AgentRunnerService(MagicMock())
        original = _run()
        ctx = _ctx(user_id=original.user_id)
        prompt = _message(role="user", content="try again")
        conversations = MagicMock()
        conversations.find_conversation = AsyncMock(return_value=None)
        conversations.model_text = AsyncMock()
        conversations.model_history = AsyncMock()

        with (
            patch(f"{MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=original)),
            patch.object(
                service, "get_run_transcript", new=AsyncMock(return_value=(original, [prompt], 1))
            ),
            patch(f"{MODULE}.ConversationService", return_value=conversations),
            patch(f"{MODULE}.load_turn_attachments", new=AsyncMock()) as attachments,
            patch.object(service, "execute", new=AsyncMock()) as execute,
            pytest.raises(NotFoundError, match="Conversation not found"),
        ):
            await service.retry_run(ctx, original.id)

        conversations.model_text.assert_not_awaited()
        conversations.model_history.assert_not_awaited()
        attachments.assert_not_awaited()
        execute.assert_not_awaited()


class TestRetryRunsTheSameRequest:
    @staticmethod
    def _service(original):
        service = AgentRunnerService(MagicMock())
        return service

    async def test_a_timed_out_run_can_be_retried(self):
        service = self._service(None)
        original = _run(status=RunStatus.TIMED_OUT.value)
        prompt = _message(role="user", content="try again")
        new_run = _run(status=RunStatus.COMPLETED.value)
        ctx = _ctx(user_id=original.user_id)
        conversations = MagicMock()
        conversations.find_conversation = AsyncMock(return_value=MagicMock())
        conversations.model_text = AsyncMock(return_value="try again")
        conversations.model_history = AsyncMock(return_value=[])

        with (
            patch(f"{MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=original)),
            patch.object(
                service, "get_run_transcript", new=AsyncMock(return_value=(original, [prompt], 1))
            ),
            patch(f"{MODULE}.ConversationService", return_value=conversations),
            patch(f"{MODULE}.load_turn_attachments", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.record_audit", new=AsyncMock()),
            patch.object(
                service, "execute", new=AsyncMock(return_value=("Done.", new_run))
            ) as executed,
            patch.object(service, "parked_calls", new=AsyncMock(return_value=[])),
        ):
            result = await service.retry_run(ctx, original.id)

        assert result.run_id == new_run.id
        assert executed.await_args.kwargs["parent_run_id"] is None
        assert executed.await_args.kwargs["retry_of_run_id"] == original.id

    async def test_the_new_run_reissues_the_original_turn(self):
        """The prompt is the original user turn as the model reads it, the
        history stops before it, its files travel with it, and the new run
        names the original as its parent - while the original row is left
        exactly as it was."""
        service = self._service(None)
        original = _run()
        prompt = _message(role="user", content="pay the invoice")
        failed = _message(role="assistant", content="Working on it, half done")
        new_run = _run(
            id=uuid.uuid4(),
            parent_run_id=None,
            retry_of_run_id=original.id,
            status=RunStatus.COMPLETED.value,
            cost_usd=Decimal("0.02"),
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=0,
            cache_write_tokens=0,
            cost_is_partial=False,
        )
        ctx = _ctx(user_id=original.user_id)
        conversations = MagicMock()
        conversations.find_conversation = AsyncMock(return_value=MagicMock())
        conversations.model_text = AsyncMock(return_value="pay the invoice")
        conversations.model_history = AsyncMock(return_value=[])
        executed = AsyncMock(return_value=("Paid.", new_run))

        with (
            patch(f"{MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=original)),
            patch.object(
                service,
                "get_run_transcript",
                new=AsyncMock(return_value=(original, [prompt, failed], 2)),
            ),
            patch(f"{MODULE}.ConversationService", return_value=conversations),
            patch(f"{MODULE}.load_turn_attachments", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.record_audit", new=AsyncMock()) as audited,
            patch.object(service, "execute", new=executed),
            patch.object(service, "parked_calls", new=AsyncMock(return_value=[])),
        ):
            result = await service.retry_run(ctx, original.id)

        assert result.run_id == new_run.id
        assert result.output == "Paid."
        conversations.model_history.assert_awaited_once()
        history_kwargs = conversations.model_history.await_args.kwargs
        assert history_kwargs["before_message_id"] == prompt.id
        assert history_kwargs["exclude_message_id"] == prompt.id
        executed.assert_awaited_once()
        execute_kwargs = executed.await_args.kwargs
        assert execute_kwargs["parent_run_id"] is None
        assert execute_kwargs["retry_of_run_id"] == original.id
        assert execute_kwargs["conversation_id"] == original.conversation_id
        assert execute_kwargs["message_history"] == []
        assert executed.await_args.args[2] == "pay the invoice"
        audited.assert_awaited_once()
        assert audited.await_args.kwargs["action"] == "run.retried"
        assert audited.await_args.kwargs["target_id"] == str(new_run.id)
        assert audited.await_args.kwargs["details"]["retried_from"] == str(original.id)

    async def test_retry_cost_is_included_in_top_level_spend(self):
        organization_id = uuid.uuid4()
        retry = _run(
            organization_id=organization_id,
            parent_run_id=None,
            retry_of_run_id=uuid.uuid4(),
            cost_usd=Decimal("0.02"),
        )
        db = MagicMock()
        db.scalar = AsyncMock(return_value=retry.cost_usd)

        total = await sum_cost_since(
            db,
            organization_id=organization_id,
            since=datetime(2026, 1, 1, tzinfo=UTC),
        )

        statement = db.scalar.await_args.args[0]
        assert "sum(agent_runs.cost_usd)" in str(statement)
        assert "agent_runs.parent_run_id IS NULL" in str(statement)
        assert total == retry.cost_usd

    async def test_the_original_turns_files_travel_with_the_retry(self):
        """A question asked with a document is the same request only with the
        document: the files are re-read off the turn that carried them."""
        service = self._service(None)
        original = _run()
        file_id = uuid.uuid4()
        prompt = _message(role="user", content="what changed?", files=[SimpleNamespace(id=file_id)])
        new_run = _run(status=RunStatus.COMPLETED.value)
        ctx = _ctx(user_id=original.user_id)
        conversations = MagicMock()
        conversations.find_conversation = AsyncMock(return_value=MagicMock())
        conversations.model_text = AsyncMock(return_value="what changed?")
        conversations.model_history = AsyncMock(return_value=[])

        with (
            patch(f"{MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=original)),
            patch.object(
                service,
                "get_run_transcript",
                new=AsyncMock(return_value=(original, [prompt], 1)),
            ),
            patch(f"{MODULE}.ConversationService", return_value=conversations),
            patch(
                f"{MODULE}.load_turn_attachments", new=AsyncMock(return_value=["file"])
            ) as attached,
            patch(f"{MODULE}.record_audit", new=AsyncMock()),
            patch.object(
                service, "execute", new=AsyncMock(return_value=("Rose.", new_run))
            ) as executed,
            patch.object(service, "parked_calls", new=AsyncMock(return_value=[])),
        ):
            await service.retry_run(ctx, original.id)

        attached.assert_awaited_once()
        assert attached.await_args.args[1] == prompt.id
        assert attached.await_args.args[2] == [str(file_id)]
        assert executed.await_args.kwargs["attachments"] == ["file"]
