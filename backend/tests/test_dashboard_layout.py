"""Unit tests for the dashboard-layout repository, service and write schema.

The behaviour worth pinning here is the tenant predicate (both ids, always),
the upsert's create-vs-replace fork, the reset's idempotence, and that a write
is refused for a widget or span the registry does not know. The schema
guarantees the database enforces - one row per person per org, the cascades -
are asserted against a real database in tests/integration/test_dashboard_layout.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.db.models.dashboard_layout import DashboardLayout
from app.repositories import dashboard_layout_repo
from app.schemas.dashboard_layout import DashboardLayoutUpdate, SectionDivider, WidgetPlacement
from app.services.dashboard_layout import DashboardLayoutService

pytestmark = pytest.mark.anyio


class _RecordingSession:
    """An `AsyncSession` stand-in that keeps the statements it was given."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.statements: list[object] = []
        self.added: list[DashboardLayout] = []
        self.deleted: list[DashboardLayout] = []

    async def execute(self, statement: object) -> object:
        self.statements.append(statement)
        return self._results.pop(0)

    def add(self, instance: DashboardLayout) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        pass

    async def refresh(self, instance: DashboardLayout) -> None:
        pass

    async def delete(self, instance: DashboardLayout) -> None:
        self.deleted.append(instance)


def _result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _filters(session: _RecordingSession) -> dict[str, object]:
    return session.statements[-1].compile(dialect=postgresql.dialect()).params


async def test_get_filters_on_both_the_user_and_the_organization() -> None:
    user_id, org_id = uuid4(), uuid4()
    session = _RecordingSession(_result(None))

    await dashboard_layout_repo.get(session, user_id=user_id, organization_id=org_id)

    # Dropping either half is a cross-tenant read; both bound values must be there.
    values = set(_filters(session).values())
    assert user_id in values
    assert org_id in values


async def test_upsert_is_a_single_atomic_on_conflict_statement() -> None:
    # Not a read-then-insert: two first saves in flight together would both read
    # no row and the second insert would 500 on the unique constraint. One
    # `INSERT ... ON CONFLICT DO UPDATE` on that constraint cannot race itself.
    user_id, org_id = uuid4(), uuid4()
    stored = DashboardLayout(user_id=user_id, organization_id=org_id, entries=[])
    result = MagicMock()
    result.scalar_one.return_value = stored
    session = _RecordingSession(result)

    returned = await dashboard_layout_repo.upsert(
        session, user_id=user_id, organization_id=org_id, entries=[{"widget": "runs", "span": "s8"}]
    )

    assert returned is stored
    assert session.added == []  # no ORM read-then-add; the database resolves the conflict
    compiled = str(session.statements[-1].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT ON CONSTRAINT uq_dashboard_layout_user_org DO UPDATE" in compiled


async def test_delete_removes_the_row() -> None:
    layout = DashboardLayout(user_id=uuid4(), organization_id=uuid4(), entries=[])
    session = _RecordingSession()

    await dashboard_layout_repo.delete(session, db_layout=layout)

    assert session.deleted == [layout]


async def test_get_for_user_returns_none_when_nothing_saved(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_layout_repo, "get", AsyncMock(return_value=None))
    service = DashboardLayoutService(MagicMock())

    assert await service.get_for_user(user_id=uuid4(), organization_id=uuid4()) is None


async def test_save_stores_the_entries_as_plain_dicts(monkeypatch) -> None:
    upsert = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(dashboard_layout_repo, "upsert", upsert)
    service = DashboardLayoutService(MagicMock())
    data = DashboardLayoutUpdate(
        entries=[{"widget": "runs", "span": "s8"}, {"widget": "spend", "span": "s6"}]
    )

    await service.save(user_id=uuid4(), organization_id=uuid4(), data=data)

    assert upsert.call_args.kwargs["entries"] == [
        {"kind": "widget", "widget": "runs", "span": "s8", "rows": None, "options": None},
        {"kind": "widget", "widget": "spend", "span": "s6", "rows": None, "options": None},
    ]


async def test_reset_deletes_an_existing_layout(monkeypatch) -> None:
    existing = MagicMock()
    monkeypatch.setattr(dashboard_layout_repo, "get", AsyncMock(return_value=existing))
    delete = AsyncMock()
    monkeypatch.setattr(dashboard_layout_repo, "delete", delete)
    service = DashboardLayoutService(MagicMock())

    await service.reset(user_id=uuid4(), organization_id=uuid4())

    assert delete.call_args.kwargs["db_layout"] is existing


async def test_reset_is_a_no_op_when_nothing_is_saved(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_layout_repo, "get", AsyncMock(return_value=None))
    delete = AsyncMock()
    monkeypatch.setattr(dashboard_layout_repo, "delete", delete)
    service = DashboardLayoutService(MagicMock())

    await service.reset(user_id=uuid4(), organization_id=uuid4())

    delete.assert_not_called()


def test_a_valid_arrangement_is_accepted() -> None:
    data = DashboardLayoutUpdate(entries=[{"widget": "runs", "span": "s8"}])
    assert isinstance(data.entries[0], WidgetPlacement)
    assert data.entries[0].widget == "runs"


def test_an_empty_arrangement_is_accepted() -> None:
    # Hiding every card is a deliberate state, not an error.
    assert DashboardLayoutUpdate(entries=[]).entries == []


def test_an_unknown_widget_id_is_refused() -> None:
    with pytest.raises(ValidationError):
        DashboardLayoutUpdate(entries=[{"widget": "not-a-widget", "span": "s8"}])


def test_a_span_outside_the_closed_set_is_refused() -> None:
    with pytest.raises(ValidationError):
        DashboardLayoutUpdate(entries=[{"widget": "runs", "span": "s9"}])


def test_an_unbounded_arrangement_is_refused() -> None:
    too_many = [{"widget": "runs", "span": "s8"} for _ in range(61)]
    with pytest.raises(ValidationError):
        DashboardLayoutUpdate(entries=too_many)


def test_a_read_returns_a_retired_widget_verbatim() -> None:
    # The read shape is permissive on purpose: a widget id valid when saved but
    # retired since is handed back, not turned into a 500 by re-validation.
    from app.schemas.dashboard_layout import DashboardLayoutRead

    read = DashboardLayoutRead.model_validate(
        DashboardLayout(
            id=uuid4(),
            user_id=uuid4(),
            organization_id=uuid4(),
            entries=[{"widget": "retired-widget", "span": "s6"}],
            created_at=datetime.now(UTC),
        )
    )
    assert read.entries[0].widget == "retired-widget"


def test_a_section_divider_is_accepted_alongside_widgets() -> None:
    # The discriminator routes `kind: "section"` to the divider member, so a
    # heading validates beside the cards rather than 422-ing as a bad widget.
    data = DashboardLayoutUpdate(
        entries=[
            {"kind": "section", "label": "Attention", "accent": "amber"},
            {"widget": "runs", "span": "s8"},
        ]
    )
    divider, widget = data.entries
    assert isinstance(divider, SectionDivider)
    assert (divider.label, divider.accent, divider.collapsed) == ("Attention", "amber", False)
    assert isinstance(widget, WidgetPlacement)


def test_a_divider_hex_accent_is_lowercased_and_a_bad_accent_is_refused() -> None:
    lowered = DashboardLayoutUpdate(entries=[{"kind": "section", "accent": "#AABBCC"}])
    assert isinstance(lowered.entries[0], SectionDivider)
    assert lowered.entries[0].accent == "#aabbcc"

    # A string that is neither "neutral", a named preset, nor a #rrggbb hex would
    # render as no colour and read as a bug, so it is refused at the boundary.
    with pytest.raises(ValidationError):
        DashboardLayoutUpdate(entries=[{"kind": "section", "accent": "chartreuse"}])
