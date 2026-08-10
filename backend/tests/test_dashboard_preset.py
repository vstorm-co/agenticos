"""Unit tests for the dashboard-preset repository, service and write schema.

What is pinned here: the tenant predicate on every query (both ids, always,
and the name or preset id on top), the two refusals "save as" depends on — a
duplicate name and the per-person cap — and that heights are validated the
same way widths are. The database-only guarantees (the unique name constraint,
the cascades) are asserted against a real database in
tests/integration/test_dashboard_preset.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from app.db.models.dashboard_preset import DashboardPreset
from app.repositories import dashboard_preset_repo
from app.schemas.dashboard_layout import MAX_PRESETS, DashboardPresetCreate, WidgetPlacement
from app.services.dashboard_preset import DashboardPresetService

pytestmark = pytest.mark.anyio


class _RecordingSession:
    """An `AsyncSession` stand-in that keeps the statements it was given."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.statements: list[object] = []
        self.added: list[DashboardPreset] = []
        self.deleted: list[DashboardPreset] = []

    async def execute(self, statement: object) -> object:
        self.statements.append(statement)
        return self._results.pop(0)

    def add(self, instance: DashboardPreset) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        pass

    async def refresh(self, instance: DashboardPreset) -> None:
        pass

    async def delete(self, instance: DashboardPreset) -> None:
        self.deleted.append(instance)


def _scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _filters(session: _RecordingSession) -> set[object]:
    return set(session.statements[-1].compile(dialect=postgresql.dialect()).params.values())


# --- repository -----------------------------------------------------------


async def test_list_filters_on_both_the_user_and_the_organization() -> None:
    user_id, org_id = uuid4(), uuid4()
    scalars = MagicMock()
    scalars.scalars.return_value.all.return_value = []
    session = _RecordingSession(scalars)

    await dashboard_preset_repo.list_for_user(session, user_id=user_id, organization_id=org_id)

    values = _filters(session)
    assert user_id in values
    assert org_id in values


async def test_get_filters_on_the_preset_the_user_and_the_organization() -> None:
    preset_id, user_id, org_id = uuid4(), uuid4(), uuid4()
    session = _RecordingSession(_scalar_result(None))

    await dashboard_preset_repo.get(
        session, preset_id=preset_id, user_id=user_id, organization_id=org_id
    )

    values = _filters(session)
    assert {preset_id, user_id, org_id} <= values


async def test_get_by_name_filters_on_the_name_inside_the_tenant_pair() -> None:
    user_id, org_id = uuid4(), uuid4()
    session = _RecordingSession(_scalar_result(None))

    await dashboard_preset_repo.get_by_name(
        session, user_id=user_id, organization_id=org_id, name="Monday review"
    )

    values = _filters(session)
    assert {user_id, org_id, "Monday review"} <= values


async def test_count_filters_on_both_the_user_and_the_organization() -> None:
    user_id, org_id = uuid4(), uuid4()
    result = MagicMock()
    result.scalar_one.return_value = 3
    session = _RecordingSession(result)

    count = await dashboard_preset_repo.count_for_user(
        session, user_id=user_id, organization_id=org_id
    )

    assert count == 3
    values = _filters(session)
    assert user_id in values
    assert org_id in values


async def test_create_adds_a_row_with_the_given_placements() -> None:
    user_id, org_id = uuid4(), uuid4()
    session = _RecordingSession()
    entries = [{"widget": "runs", "span": "s8", "rows": "r3"}]

    created = await dashboard_preset_repo.create(
        session, user_id=user_id, organization_id=org_id, name="Monday review", entries=entries
    )

    assert session.added == [created]
    assert created.name == "Monday review"
    assert created.entries == entries


async def test_delete_removes_the_row() -> None:
    preset = DashboardPreset(user_id=uuid4(), organization_id=uuid4(), name="x", entries=[])
    session = _RecordingSession()

    await dashboard_preset_repo.delete(session, db_preset=preset)

    assert session.deleted == [preset]


# --- service --------------------------------------------------------------


def _create_data(name: str = "Monday review") -> DashboardPresetCreate:
    return DashboardPresetCreate(name=name, entries=[{"widget": "runs", "span": "s8"}])


async def test_creating_under_a_name_already_used_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_preset_repo, "get_by_name", AsyncMock(return_value=MagicMock()))
    create = AsyncMock()
    monkeypatch.setattr(dashboard_preset_repo, "create", create)
    service = DashboardPresetService(MagicMock())

    with pytest.raises(AlreadyExistsError):
        await service.create(user_id=uuid4(), organization_id=uuid4(), data=_create_data())

    create.assert_not_called()


async def test_creating_past_the_cap_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_preset_repo, "get_by_name", AsyncMock(return_value=None))
    monkeypatch.setattr(
        dashboard_preset_repo, "count_for_user", AsyncMock(return_value=MAX_PRESETS)
    )
    create = AsyncMock()
    monkeypatch.setattr(dashboard_preset_repo, "create", create)
    service = DashboardPresetService(MagicMock())

    with pytest.raises(ValidationError):
        await service.create(user_id=uuid4(), organization_id=uuid4(), data=_create_data())

    create.assert_not_called()


async def test_a_duplicate_name_racing_past_the_check_is_still_a_409(monkeypatch) -> None:
    # The get-by-name check is not atomic: two concurrent saves both pass it and
    # the unique constraint refuses the second insert. That IntegrityError must
    # become the same 409 the check raises, not a 500.
    monkeypatch.setattr(dashboard_preset_repo, "get_by_name", AsyncMock(return_value=None))
    monkeypatch.setattr(dashboard_preset_repo, "count_for_user", AsyncMock(return_value=0))
    monkeypatch.setattr(
        dashboard_preset_repo,
        "create",
        AsyncMock(side_effect=IntegrityError("insert", {}, Exception("duplicate key"))),
    )
    service = DashboardPresetService(MagicMock())

    with pytest.raises(AlreadyExistsError):
        await service.create(user_id=uuid4(), organization_id=uuid4(), data=_create_data())


async def test_creating_stores_the_placements_as_plain_dicts(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_preset_repo, "get_by_name", AsyncMock(return_value=None))
    monkeypatch.setattr(dashboard_preset_repo, "count_for_user", AsyncMock(return_value=0))
    create = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(dashboard_preset_repo, "create", create)
    service = DashboardPresetService(MagicMock())
    data = DashboardPresetCreate(
        name="Monday review",
        entries=[{"widget": "runs", "span": "s8", "rows": "r4"}, {"widget": "spend", "span": "s6"}],
    )

    await service.create(user_id=uuid4(), organization_id=uuid4(), data=data)

    assert create.call_args.kwargs["entries"] == [
        {"kind": "widget", "widget": "runs", "span": "s8", "rows": "r4"},
        {"kind": "widget", "widget": "spend", "span": "s6", "rows": None},
    ]


async def test_listing_returns_the_presets_with_their_count(monkeypatch) -> None:
    presets = [MagicMock(), MagicMock()]
    monkeypatch.setattr(dashboard_preset_repo, "list_for_user", AsyncMock(return_value=presets))
    service = DashboardPresetService(MagicMock())

    items, total = await service.list_for_user(user_id=uuid4(), organization_id=uuid4())

    assert items == presets
    assert total == 2


async def test_deleting_a_preset_outside_the_callers_scope_is_a_404(monkeypatch) -> None:
    # The repo's filter answers None for another org's preset even when the
    # caller owns the row - the service must turn that into NotFound, never
    # reach for the row another way.
    monkeypatch.setattr(dashboard_preset_repo, "get", AsyncMock(return_value=None))
    delete = AsyncMock()
    monkeypatch.setattr(dashboard_preset_repo, "delete", delete)
    service = DashboardPresetService(MagicMock())

    with pytest.raises(NotFoundError):
        await service.delete(user_id=uuid4(), organization_id=uuid4(), preset_id=uuid4())

    delete.assert_not_called()


async def test_deleting_an_owned_preset_removes_it(monkeypatch) -> None:
    preset = MagicMock()
    monkeypatch.setattr(dashboard_preset_repo, "get", AsyncMock(return_value=preset))
    delete = AsyncMock()
    monkeypatch.setattr(dashboard_preset_repo, "delete", delete)
    service = DashboardPresetService(MagicMock())

    await service.delete(user_id=uuid4(), organization_id=uuid4(), preset_id=uuid4())

    assert delete.call_args.kwargs["db_preset"] is preset


# --- write schema ---------------------------------------------------------


def test_a_placement_height_outside_the_closed_set_is_refused() -> None:
    with pytest.raises(PydanticValidationError):
        WidgetPlacement(widget="runs", span="s8", rows="r9")


def test_a_placement_without_a_height_is_accepted() -> None:
    # Arrangements saved before heights existed carry no `rows`; the widget's
    # default height applies at render time.
    assert WidgetPlacement(widget="runs", span="s8").rows is None


def test_a_preset_name_is_bounded() -> None:
    with pytest.raises(PydanticValidationError):
        DashboardPresetCreate(name="", entries=[])
    with pytest.raises(PydanticValidationError):
        DashboardPresetCreate(name="x" * 61, entries=[])


def test_a_preset_validates_its_placements_like_the_active_layout() -> None:
    with pytest.raises(PydanticValidationError):
        DashboardPresetCreate(name="ok", entries=[{"widget": "not-a-widget", "span": "s8"}])
