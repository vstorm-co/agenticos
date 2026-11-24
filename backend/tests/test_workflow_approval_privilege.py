"""A workflow approval is somebody else's work: only a privileged decider decides one.

A member holds `approvals:decide` at `OWN`, for the tool calls of a run they
started. That does not reach a workflow step, whether the step names approvers
or nobody at all, and it does not make the organization's queue theirs to list.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, OrgRoleName, Perm
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


async def _decide(ctx: AuthContext, approval: MagicMock) -> None:
    """`decide()` on a row loaded at the repository boundary; every case here is refused."""
    with patch(f"{_MODULE}.approval_repo.get_for_update", new=AsyncMock(return_value=approval)):
        await WorkflowApprovalService(MagicMock()).decide(ctx, uuid.uuid4(), approved=True)


async def test_a_member_named_as_the_approver_is_refused_by_decide() -> None:
    ctx = _ctx(OrgRoleName.MEMBER.value)
    approval = MagicMock(approver_user_ids=[ctx.subject_id], approver_group_ids=[])

    with pytest.raises(AuthorizationError, match="people this step names"):
        await _decide(ctx, approval)


async def test_a_member_is_refused_by_decide_when_the_step_names_nobody() -> None:
    approval = MagicMock(approver_user_ids=[], approver_group_ids=[])

    with pytest.raises(AuthorizationError, match="people this step names"):
        await _decide(_ctx(OrgRoleName.MEMBER.value), approval)


async def test_a_named_approvers_key_without_the_permission_is_refused_by_decide() -> None:
    """The role could decide, the key was issued for something narrower, and the step names them."""
    user_id = uuid.uuid4()
    ctx = AuthContext(
        user_id=user_id,
        organization_id=uuid.uuid4(),
        role=OrgRoleName.OWNER.value,
        api_key_id=uuid.uuid4(),
        key_scopes=frozenset({Perm.AGENTS_VIEW}),
    )
    approval = MagicMock(approver_user_ids=[user_id], approver_group_ids=[])

    service = WorkflowApprovalService(MagicMock())
    without_key = AuthContext(user_id=user_id, organization_id=ctx.organization_id, role="owner")
    assert await service._eligible(without_key, approval) is True
    assert await service._eligible(ctx, approval) is False
    with pytest.raises(AuthorizationError, match="people this step names"):
        await _decide(ctx, approval)
