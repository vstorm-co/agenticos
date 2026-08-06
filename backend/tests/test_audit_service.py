"""Reading the audit trail, and the scope that reading it depends on.

The `/audit` route used to hold both queries itself and pass
`organization_id=ctx.organization_id` twice. Nothing was wrong with the value; the
problem is that no test of the log could see it, so "an entry belongs to exactly
one organization" was a property of one handler rather than of the log (#232).

These tests are what makes it a property of the service: the organization comes off
the auth context, and there is no argument through which a caller could name
another one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.permissions import AuthContext, OrgRoleName
from app.services.audit import AuditService

pytestmark = pytest.mark.anyio


def _ctx(org_id: uuid.UUID | None = None) -> AuthContext:
    return AuthContext(
        user_id=uuid.uuid4(),
        organization_id=org_id or uuid.uuid4(),
        role=OrgRoleName.OWNER,
    )


def _entry(*, action: str = "agent.published") -> MagicMock:
    entry = MagicMock()
    entry.id = uuid.uuid4()
    entry.actor_user_id = uuid.uuid4()
    entry.action = action
    entry.target_type = "agent"
    entry.target_id = str(uuid.uuid4())
    entry.details = {"version": 3}
    entry.created_at = datetime.now(UTC)
    return entry


async def test_an_entry_is_reported_as_the_page_it_belongs_to() -> None:
    entry = _entry()

    with (
        patch(
            "app.services.audit.audit_log_repo.list_for_org",
            new=AsyncMock(return_value=[entry]),
        ),
        patch("app.services.audit.audit_log_repo.count_for_org", new=AsyncMock(return_value=1)),
    ):
        page = await AuditService(MagicMock()).list_for_organization(_ctx())

    assert [item.action for item in page.items] == ["agent.published"]
    assert page.items[0].details == {"version": 3}
    assert page.total == 1


async def test_the_organization_read_is_the_callers_own() -> None:
    """The only tenant boundary this service has, and it is not an argument."""
    ctx = _ctx()

    with (
        patch(
            "app.services.audit.audit_log_repo.list_for_org", new=AsyncMock(return_value=[])
        ) as listed,
        patch(
            "app.services.audit.audit_log_repo.count_for_org", new=AsyncMock(return_value=0)
        ) as counted,
    ):
        await AuditService(MagicMock()).list_for_organization(ctx, skip=20, limit=10)

    assert listed.await_args.kwargs == {
        "organization_id": ctx.organization_id,
        "skip": 20,
        "limit": 10,
    }
    assert counted.await_args.kwargs == {"organization_id": ctx.organization_id}


async def test_the_total_is_the_whole_log_rather_than_the_page() -> None:
    """A page of fifty out of two hundred has to say two hundred.

    `len(items)` would agree with the total on every first page and disagree on
    every last one, which is the version of this bug nobody notices until the log
    is longer than one screen.
    """
    with (
        patch(
            "app.services.audit.audit_log_repo.list_for_org",
            new=AsyncMock(return_value=[_entry(), _entry()]),
        ),
        patch("app.services.audit.audit_log_repo.count_for_org", new=AsyncMock(return_value=207)),
    ):
        page = await AuditService(MagicMock()).list_for_organization(_ctx(), limit=2)

    assert len(page.items) == 2
    assert page.total == 207


async def test_an_organization_with_no_entries_answers_empty() -> None:
    with (
        patch("app.services.audit.audit_log_repo.list_for_org", new=AsyncMock(return_value=[])),
        patch("app.services.audit.audit_log_repo.count_for_org", new=AsyncMock(return_value=0)),
    ):
        page = await AuditService(MagicMock()).list_for_organization(_ctx())

    assert page.items == []
    assert page.total == 0
