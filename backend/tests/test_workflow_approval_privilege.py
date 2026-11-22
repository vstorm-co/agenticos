"""A workflow approval is somebody else's work: only a privileged decider decides one.

A member holds `approvals:decide` at `OWN`, for the tool calls of a run they
started. That does not reach a workflow step, whether the step names approvers
or nobody at all, and it does not make the organization's queue theirs to list.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.permissions import AuthContext, OrgRoleName
from app.services.workflow_execution.approvals import WorkflowApprovalService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_MODULE = "app.services.workflow_execution.approvals"


def _ctx(role: str) -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)


async def test_a_member_is_not_eligible_to_decide_a_workflow_step() -> None:
    approval = MagicMock(approver_user_ids=[], approver_group_ids=[])

    eligible = await WorkflowApprovalService(MagicMock())._eligible(
        _ctx(OrgRoleName.MEMBER.value), approval
    )

    assert eligible is False


async def test_a_member_reading_the_queue_gets_only_what_names_them_and_decides_none_of_it() -> (
    None
):
    ctx = _ctx(OrgRoleName.MEMBER.value)
    row = MagicMock(approver_user_ids=[ctx.subject_id], approver_group_ids=[])
    listed = AsyncMock(return_value=([(row, "Refund review")], 1))
    seen: list[bool] = []

    def read(_row: object, _name: str, *, can_decide: bool) -> MagicMock:
        seen.append(can_decide)
        return MagicMock()

    with (
        patch(f"{_MODULE}.approval_repo.list_with_workflow", new=listed),
        patch(f"{_MODULE}.groups_deciding_through", new=AsyncMock(return_value=set())),
        patch(f"{_MODULE}._read", new=read),
        patch(f"{_MODULE}.WorkflowApprovalList", new=MagicMock()),
    ):
        await WorkflowApprovalService(MagicMock()).queue(ctx, statuses=[], decidable=False)

    assert listed.await_args.kwargs["decidable_by"] == ctx.subject_id
    assert seen == [False]
