"""What reading a run's transcript decides, at the service layer.

Authorization for a run is the organization's, not the starter's: a colleague
holding `runs:view` reads a run somebody else began. The refusals are what carry
that promise, and their order is the point of the whole issue. Existence is
resolved against the caller's organization *before* the permission is read, so a
run in another tenant reads as absent - the same `NotFoundError`, down to its
`details`, that an id which never existed raises - rather than as forbidden,
which would confirm the id to a stranger. Only once the run is known to be the
caller's organization's does a missing `runs:view` become a 403.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.services import agent_runner
from app.services.agent_runner import AgentRunnerService

pytestmark = pytest.mark.anyio

_ORG = uuid4()


def _ctx(*, role: str, user_id: UUID | None = None) -> AuthContext:
    return AuthContext(user_id=user_id or uuid4(), organization_id=_ORG, role=role)


def _run(*, conversation_id: UUID | None = None, owner_id: UUID | None = None) -> MagicMock:
    return MagicMock(id=uuid4(), conversation_id=conversation_id, user_id=owner_id or uuid4())


async def test_a_colleague_holding_runs_view_reads_a_run_they_did_not_start(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncMock
) -> None:
    colleague = uuid4()
    run = _run(conversation_id=uuid4(), owner_id=uuid4())
    message = MagicMock()
    monkeypatch.setattr(agent_runner.agent_run_repo, "get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(
        agent_runner.conversation_repo, "get_messages_by_run", AsyncMock(return_value=[message])
    )
    monkeypatch.setattr(
        agent_runner.conversation_repo, "count_messages_by_run", AsyncMock(return_value=1)
    )

    got_run, messages, total = await AgentRunnerService(mock_db_session).get_run_transcript(
        _ctx(role=OrgRoleName.OPERATOR.value, user_id=colleague), run.id
    )

    assert run.user_id != colleague
    assert (got_run, messages, total) == (run, [message], 1)
    # Fetched scoped to the caller's organization - which is what makes a foreign
    # run read as absent rather than forbidden.
    assert agent_runner.agent_run_repo.get_run.await_args.kwargs["organization_id"] == _ORG


async def test_the_conversation_scope_reads_the_whole_thread_the_run_sits_in(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncMock
) -> None:
    """A convenience, not a reach: every turn a run writes carries its run_id,
    so the thread was already assemblable by iterating its runs' transcripts
    under the same runs:view."""
    run = _run(conversation_id=uuid4())
    thread = [MagicMock(), MagicMock(), MagicMock()]
    monkeypatch.setattr(agent_runner.agent_run_repo, "get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(
        agent_runner.conversation_repo,
        "get_messages_by_conversation",
        AsyncMock(return_value=thread),
    )
    monkeypatch.setattr(agent_runner.conversation_repo, "count_messages", AsyncMock(return_value=3))

    _, messages, total = await AgentRunnerService(mock_db_session).get_run_transcript(
        _ctx(role=OrgRoleName.OPERATOR.value), run.id, whole_conversation=True
    )

    assert (messages, total) == (thread, 3)
    call = agent_runner.conversation_repo.get_messages_by_conversation.await_args
    assert call.args[1] == run.conversation_id
    assert call.kwargs["include_tool_calls"] is True


async def test_a_missing_or_foreign_run_is_a_not_found_naming_only_the_id(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncMock
) -> None:
    """The 404 body, which cross-tenant and never-existed must share exactly: a
    tenant that could tell a neighbour's run from a fictional one has leaked its
    existence."""
    run_id = uuid4()
    monkeypatch.setattr(agent_runner.agent_run_repo, "get_run", AsyncMock(return_value=None))

    with pytest.raises(NotFoundError) as caught:
        await AgentRunnerService(mock_db_session).get_run_transcript(
            _ctx(role=OrgRoleName.OPERATOR.value), run_id
        )

    assert caught.value.message == "Run not found"
    assert caught.value.details == {"run_id": str(run_id)}


async def test_an_absent_run_is_not_found_before_the_permission_is_read(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncMock
) -> None:
    """A caller without `runs:view` asking for a run outside their organization
    gets the same 404 as anyone else, not a 403 - the existence check runs first,
    so the permission never gets to confirm the id."""
    monkeypatch.setattr(agent_runner.agent_run_repo, "get_run", AsyncMock(return_value=None))

    with pytest.raises(NotFoundError):
        await AgentRunnerService(mock_db_session).get_run_transcript(
            _ctx(role=OrgRoleName.VIEWER.value), uuid4()
        )


async def test_a_caller_without_runs_view_is_refused_once_the_run_is_theirs(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncMock
) -> None:
    run = _run(conversation_id=uuid4())
    monkeypatch.setattr(agent_runner.agent_run_repo, "get_run", AsyncMock(return_value=run))
    fetch = AsyncMock()
    monkeypatch.setattr(agent_runner.conversation_repo, "get_messages_by_run", fetch)

    with pytest.raises(AuthorizationError) as caught:
        await AgentRunnerService(mock_db_session).get_run_transcript(
            _ctx(role=OrgRoleName.VIEWER.value), run.id
        )

    assert caught.value.details == {"required": [Perm.RUNS_VIEW.value], "run_id": str(run.id)}
    fetch.assert_not_awaited()


async def test_a_run_with_no_conversation_reports_no_transcript(
    monkeypatch: pytest.MonkeyPatch, mock_db_session: AsyncMock
) -> None:
    """A run started with no conversation has no transcript by construction - the
    runner never writes a turn for one - so the emptiness is reported through a
    null `conversation_id`, and the message read is skipped rather than run to
    confirm a certainty."""
    run = _run(conversation_id=None)
    monkeypatch.setattr(agent_runner.agent_run_repo, "get_run", AsyncMock(return_value=run))
    fetch = AsyncMock()
    monkeypatch.setattr(agent_runner.conversation_repo, "get_messages_by_run", fetch)

    got_run, messages, total = await AgentRunnerService(mock_db_session).get_run_transcript(
        _ctx(role=OrgRoleName.OPERATOR.value), run.id
    )

    assert (got_run.conversation_id, messages, total) == (None, [], 0)
    fetch.assert_not_awaited()
