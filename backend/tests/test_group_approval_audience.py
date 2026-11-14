"""Groups resolve current eligible approvers; alert audiences never grant authority."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.spec import AlertSpec
from app.services.notifications import NotificationService
from app.services.workflow_execution import approval_audience

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_groups_are_scoped_and_only_current_deciders_are_eligible(monkeypatch):
    org, group, admin, viewer = uuid4(), uuid4(), uuid4(), uuid4()
    members = AsyncMock(return_value=[(admin, "admin"), (viewer, "viewer"), (admin, "owner")])
    monkeypatch.setattr(approval_audience.group_repo, "audience_members", members)
    assert await approval_audience.group_approvers(
        AsyncMock(), organization_id=org, group_ids=[group]
    ) == {admin}
    assert members.await_args.kwargs == {"organization_id": org, "group_ids": [group]}
    names = AsyncMock(return_value={group: "Finance"})
    monkeypatch.setattr(approval_audience.group_repo, "get_names", names)
    absent = uuid4()
    assert await approval_audience.check_groups(
        AsyncMock(), organization_id=org, group_ids=(group, absent)
    ) == [("approver_groups.1", "This group is not in the organization")]
    assert (
        await approval_audience.check_groups(AsyncMock(), organization_id=org, group_ids=(group,))
        == []
    )


async def test_alert_groups_deduplicate_with_named_people_and_do_not_filter_by_approval_permission(
    monkeypatch,
):
    from app.services import notifications

    org, group, viewer = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(
        notifications.group_repo, "audience_members", AsyncMock(return_value=[(viewer, "viewer")])
    )
    scoped = AsyncMock(return_value=[viewer])
    monkeypatch.setattr(notifications.member_repo, "list_member_ids_for", scoped)
    alert = AlertSpec(to=["chosen"], user_ids=[viewer], group_ids=[group])
    assert await NotificationService(AsyncMock())._audience_ids(
        alert, organization_id=org, owner_user_id=None, initiator_user_id=None
    ) == {viewer}
    assert scoped.await_args.kwargs["organization_id"] == org
    assert set(scoped.await_args.kwargs["user_ids"]) == {viewer}
    assert AlertSpec(to=["chosen"], group_ids=[group]).group_ids == [group]
    with pytest.raises(ValidationError):
        AlertSpec(to=["admins"], group_ids=[group])
