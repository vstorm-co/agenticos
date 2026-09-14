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


class TestExport:
    """The trail an auditor takes away, and the record that it was taken."""

    _WINDOW = (datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 31, tzinfo=UTC))

    async def _export(self, entry: MagicMock, *, fmt: str, total: int = 1):
        with (
            patch(
                "app.services.audit.audit_log_repo.list_in_window_for_org",
                new=AsyncMock(return_value=([entry], total)),
            ) as listed,
            patch("app.services.audit.record_audit", new=AsyncMock()) as audited,
        ):
            result = await AuditService(MagicMock()).export(
                _ctx(), since=self._WINDOW[0], until=self._WINDOW[1], fmt=fmt
            )
        return result, listed, audited

    async def test_csv_carries_the_header_and_the_entry(self) -> None:
        entry = _entry(action="agent.deleted")
        result, _listed, _audited = await self._export(entry, fmt="csv")

        lines = result.content.splitlines()
        assert lines[0].startswith("entry_id,created_at,actor_user_id")
        assert "agent.deleted" in lines[1]
        assert result.filename.endswith(".csv")
        assert result.row_count == 1

    async def test_csv_flattens_details_to_a_json_string(self) -> None:
        entry = _entry()
        result, _listed, _audited = await self._export(entry, fmt="csv")

        # `details` is one CSV cell holding JSON, not spread across columns.
        assert '{""version"": 3}' in result.content

    async def test_jsonl_keeps_details_a_nested_object(self) -> None:
        entry = _entry()
        result, _listed, _audited = await self._export(entry, fmt="jsonl")

        assert result.filename.endswith(".jsonl")
        assert '"details": {"version": 3}' in result.content
        assert result.content.endswith("\n")

    async def test_the_export_is_itself_audited(self) -> None:
        """Reading a whole trail is a privileged act; the record of who took it
        away names the window and the count, never a row."""
        _result, _listed, audited = await self._export(_entry(), fmt="csv")

        assert audited.await_args.kwargs["action"] == "audit.export"
        details = audited.await_args.kwargs["details"]
        assert details["format"] == "csv"
        assert details["row_count"] == 1
        assert "actor_user_id" not in details

    async def test_the_window_read_is_the_callers_own_organization(self) -> None:
        ctx = _ctx()
        with (
            patch(
                "app.services.audit.audit_log_repo.list_in_window_for_org",
                new=AsyncMock(return_value=([], 0)),
            ) as listed,
            patch("app.services.audit.record_audit", new=AsyncMock()),
        ):
            await AuditService(MagicMock()).export(
                ctx, since=self._WINDOW[0], until=self._WINDOW[1], fmt="csv"
            )

        assert listed.await_args.kwargs["organization_id"] == ctx.organization_id

    async def test_a_missing_date_range_is_refused(self) -> None:
        from app.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            await AuditService(MagicMock()).export(_ctx(), since=None, until=None, fmt="csv")

    async def test_a_match_over_the_cap_is_refused(self) -> None:
        from app.core.exceptions import ExportTooLargeError
        from app.services.exporting import MAX_EXPORT_ROWS

        with (
            patch(
                "app.services.audit.audit_log_repo.list_in_window_for_org",
                new=AsyncMock(return_value=([], MAX_EXPORT_ROWS + 1)),
            ),
            patch("app.services.audit.record_audit", new=AsyncMock()) as audited,
            pytest.raises(ExportTooLargeError),
        ):
            await AuditService(MagicMock()).export(
                _ctx(), since=self._WINDOW[0], until=self._WINDOW[1], fmt="csv"
            )

        # Refused before it read the whole table or recorded a bulk read that did
        # not happen.
        audited.assert_not_called()
