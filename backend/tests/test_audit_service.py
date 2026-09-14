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

from app.core.audit import chain_hash
from app.core.permissions import AuthContext, OrgRoleName
from app.services.audit import AuditService

pytestmark = pytest.mark.anyio


def _ctx(org_id: uuid.UUID | None = None) -> AuthContext:
    return AuthContext(
        user_id=uuid.uuid4(),
        organization_id=org_id or uuid.uuid4(),
        role=OrgRoleName.OWNER,
    )


def _entry(
    *, action: str = "agent.published", impersonator_user_id: uuid.UUID | None = None
) -> MagicMock:
    entry = MagicMock()
    entry.id = uuid.uuid4()
    entry.actor_user_id = uuid.uuid4()
    entry.impersonator_user_id = impersonator_user_id
    entry.action = action
    entry.target_type = "agent"
    entry.target_id = str(uuid.uuid4())
    entry.details = {"version": 3}
    entry.created_at = datetime.now(UTC)
    return entry


async def test_an_impersonated_entry_reports_who_was_acting() -> None:
    """The read half of #943: the trail names the administrator behind the
    account an impersonated action was recorded as."""
    admin_id = uuid.uuid4()
    entry = _entry(action="agent.deleted", impersonator_user_id=admin_id)

    with (
        patch(
            "app.services.audit.audit_log_repo.list_for_org",
            new=AsyncMock(return_value=[entry]),
        ),
        patch("app.services.audit.audit_log_repo.count_for_org", new=AsyncMock(return_value=1)),
    ):
        page = await AuditService(MagicMock()).list_for_organization(_ctx())

    assert page.items[0].impersonator_user_id == admin_id
    assert page.items[0].actor_user_id == entry.actor_user_id


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


def _linked_chain(organization_id: uuid.UUID | None, count: int) -> list[MagicMock]:
    """A correctly linked chain of `count` entries, hashed the way `record_audit`
    would have hashed them - so an untouched one verifies and a test can then break
    exactly one entry."""
    entries: list[MagicMock] = []
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    prev_hash: str | None = None
    for index in range(count):
        entry = MagicMock()
        entry.id = uuid.uuid4()
        entry.seq = index + 1
        entry.actor_user_id = uuid.uuid4()
        entry.impersonator_user_id = None
        entry.organization_id = organization_id
        entry.action = f"action.{index}"
        entry.target_type = None
        entry.target_id = None
        entry.details = None
        entry.ip_address = None
        entry.created_at = created_at
        entry.prev_hash = prev_hash
        entry.entry_hash = chain_hash(
            prev_hash=prev_hash,
            actor_user_id=entry.actor_user_id,
            impersonator_user_id=None,
            organization_id=organization_id,
            action=entry.action,
            target_type=None,
            target_id=None,
            details=None,
            ip_address=None,
            created_at=created_at,
        )
        prev_hash = entry.entry_hash
        entries.append(entry)
    return entries


async def test_an_intact_chain_verifies_with_no_break() -> None:
    org = uuid.uuid4()
    with patch(
        "app.services.audit.audit_log_repo.chain_for_org",
        new=AsyncMock(return_value=_linked_chain(org, 4)),
    ):
        result = await AuditService(MagicMock()).verify_chain(org)

    assert result.first_break is None
    assert result.entries_checked == 4
    assert result.organization_id == org


async def test_an_empty_chain_verifies() -> None:
    with patch("app.services.audit.audit_log_repo.chain_for_org", new=AsyncMock(return_value=[])):
        result = await AuditService(MagicMock()).verify_chain(uuid.uuid4())

    assert result.first_break is None
    assert result.entries_checked == 0


async def test_a_rewritten_entry_is_caught_by_its_own_hash() -> None:
    """Editing a field leaves the stored `entry_hash` describing the old contents,
    so recomputing over the new contents diverges - and the walk names that row."""
    org = uuid.uuid4()
    entries = _linked_chain(org, 4)
    entries[2].action = "action.tampered"

    with patch(
        "app.services.audit.audit_log_repo.chain_for_org", new=AsyncMock(return_value=entries)
    ):
        result = await AuditService(MagicMock()).verify_chain(org)

    assert result.first_break is not None
    assert result.first_break.seq == entries[2].seq
    assert result.first_break.entry_id == entries[2].id
    assert "entry_hash" in result.first_break.reason
    assert result.entries_checked == 3


async def test_a_broken_link_is_caught_by_prev_hash() -> None:
    """A deleted or reordered entry leaves the next one's `prev_hash` pointing at a
    hash the walk never arrives with."""
    org = uuid.uuid4()
    entries = _linked_chain(org, 4)
    entries[2].prev_hash = "0" * 64

    with patch(
        "app.services.audit.audit_log_repo.chain_for_org", new=AsyncMock(return_value=entries)
    ):
        result = await AuditService(MagicMock()).verify_chain(org)

    assert result.first_break is not None
    assert result.first_break.seq == entries[2].seq
    assert "prev_hash" in result.first_break.reason
    assert result.entries_checked == 3


async def test_verify_all_walks_every_chain_with_the_deployment_chain_first() -> None:
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    chains = {
        None: _linked_chain(None, 1),
        org_a: _linked_chain(org_a, 2),
        org_b: _linked_chain(org_b, 3),
    }

    async def _chain_for_org(_db: object, *, organization_id: uuid.UUID | None) -> list[MagicMock]:
        return chains[organization_id]

    with (
        patch(
            "app.services.audit.audit_log_repo.distinct_organization_ids",
            new=AsyncMock(return_value=[org_a, None, org_b]),
        ),
        patch("app.services.audit.audit_log_repo.chain_for_org", new=_chain_for_org),
    ):
        results = await AuditService(MagicMock()).verify_all_chains()

    assert [result.organization_id for result in results] == [
        None,
        *sorted([org_a, org_b], key=str),
    ]
    assert all(result.first_break is None for result in results)
