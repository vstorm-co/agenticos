"""What a waived call leaves behind (#925).

`ApprovalMode.APPROVE_ALL` grants every gated call in advance, and the row is
what keeps that honest: a waived run and an agent nobody ever gated are the same
run to anybody reading afterwards unless the row says which. So each grant is
written `approved`, naming the account that consented and saying it was a
standing consent rather than a click - `docs/governance.md`'s audit trail
otherwise quietly stops being one.

Written through the same path a parked call takes, because that is the property
worth pinning: `_write_approvals` is the one place rows are made, and a second
writer for waived calls would be a second thing to keep in step.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.agent_run import ApprovalDecidedVia, ApprovalStatus
from app.services.agent_runner import AgentRunnerService, ApprovalChannel, ParkedApproval

pytestmark = pytest.mark.anyio


def _prepared(channel: ApprovalChannel) -> MagicMock:
    return MagicMock(approvals=channel)


async def test_a_waived_call_is_written_approved_and_named() -> None:
    consenter = uuid.uuid4()
    channel = ApprovalChannel(
        organization_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        standing_consent_by=consenter,
    )
    channel.requested.append(
        ParkedApproval(
            approval_id=uuid.uuid4(),
            tool_call_id="call-1",
            tool_name="send_email",
            tool_args={"to": "customer@example.com"},
            standing=True,
        )
    )
    service = AgentRunnerService(MagicMock())

    with (
        patch(
            "app.services.agent_runner.agent_repo.existing_ids_locked",
            new=AsyncMock(return_value=set()),
        ),
        patch.object(service.approvals, "request", new=AsyncMock()) as written,
    ):
        await service._write_approvals(_prepared(channel))

    assert written.await_args.kwargs["standing_consent_by"] == consenter
    # The arguments too: nobody read them before they ran, so the row is the only
    # place somebody can read what they consented to.
    assert written.await_args.kwargs["tool_args"] == {"to": "customer@example.com"}


async def test_a_parked_call_on_the_same_run_names_nobody() -> None:
    """A run can hold both: the mode was set mid-conversation, or a delegate's
    call reached the channel before it. The rows have to differ."""
    channel = ApprovalChannel(
        organization_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        standing_consent_by=uuid.uuid4(),
    )
    channel.requested.extend(
        [
            ParkedApproval(
                approval_id=uuid.uuid4(),
                tool_call_id="call-1",
                tool_name="send_email",
                tool_args={},
                standing=True,
            ),
            ParkedApproval(
                approval_id=uuid.uuid4(),
                tool_call_id="call-2",
                tool_name="delete_file",
                tool_args={},
                standing=False,
            ),
        ]
    )
    service = AgentRunnerService(MagicMock())

    with (
        patch(
            "app.services.agent_runner.agent_repo.existing_ids_locked",
            new=AsyncMock(return_value=set()),
        ),
        patch.object(service.approvals, "request", new=AsyncMock()) as written,
    ):
        await service._write_approvals(_prepared(channel))

    consented = [call.kwargs["standing_consent_by"] for call in written.await_args_list]
    assert consented[0] is not None
    assert consented[1] is None


async def test_the_row_the_repository_writes_says_how_it_was_decided(mock_db_session) -> None:
    """One level down, where the columns are actually set: `approved`, the
    consenting account, a decision time, and `standing` rather than `click`."""
    from app.repositories import agent_run as agent_run_repo

    consenter = uuid.uuid4()

    row = await agent_run_repo.create_approval(
        mock_db_session,
        approval_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        tool_id="send_email",
        tool_args={"to": "customer@example.com"},
        standing_consent_by=consenter,
    )

    assert row.status == ApprovalStatus.APPROVED.value
    assert row.decided_by_user_id == consenter
    assert row.decided_at is not None
    assert row.decided_via == ApprovalDecidedVia.STANDING.value


async def test_a_pending_row_still_says_click(mock_db_session) -> None:
    """Every decision so far was somebody pressing a button, and a pending row is
    one waiting for exactly that - so `click` is the honest default rather than a
    third value meaning "not yet"."""
    from app.repositories import agent_run as agent_run_repo

    row = await agent_run_repo.create_approval(
        mock_db_session,
        approval_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        tool_id="send_email",
        tool_args={},
    )

    assert row.status == ApprovalStatus.PENDING.value
    assert row.decided_by_user_id is None
    assert row.decided_at is None
    assert row.decided_via == ApprovalDecidedVia.CLICK.value
