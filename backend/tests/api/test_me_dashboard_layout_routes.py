"""The route contract for /me/dashboard-layout and its /presets shelf.

The services are stubbed; what is under test is the routes' own behaviour -
that no saved layout is a 404 the frontend reads as "use the default", that a
write naming a widget, span or height the registry does not know is refused at
the boundary rather than stored, that reset answers 204, and that the preset
refusals (duplicate name, the cap) surface with their status codes. Tenant
isolation through a real database is tests/integration/test_dashboard_layout.py
and tests/integration/test_dashboard_preset.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from app.db.models.dashboard_layout import DashboardLayout
from app.db.models.dashboard_preset import DashboardPreset
from app.main import app
from app.schemas.dashboard_layout import MAX_PRESETS

pytestmark = pytest.mark.anyio

_USER_ID = uuid4()
_ORG_ID = uuid4()


def _layout(entries: list[dict[str, Any]]) -> DashboardLayout:
    return DashboardLayout(
        id=uuid4(),
        user_id=_USER_ID,
        organization_id=_ORG_ID,
        entries=entries,
        created_at=datetime.now(UTC),
    )


def _preset(name: str, entries: list[dict[str, Any]]) -> DashboardPreset:
    return DashboardPreset(
        id=uuid4(),
        user_id=_USER_ID,
        organization_id=_ORG_ID,
        name=name,
        entries=entries,
        created_at=datetime.now(UTC),
    )


@asynccontextmanager
async def _client(
    service: MagicMock, presets: MagicMock | None = None
) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[deps.get_current_user] = lambda: MagicMock(id=_USER_ID)
    app.dependency_overrides[deps.get_active_organization] = lambda: MagicMock(id=_ORG_ID)
    app.dependency_overrides[deps.get_dashboard_layout_service] = lambda: service
    app.dependency_overrides[deps.get_dashboard_preset_service] = lambda: (
        presets if presets is not None else _preset_service()
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _service() -> MagicMock:
    service = MagicMock()
    service.get_for_user = AsyncMock(return_value=None)
    service.save = AsyncMock(return_value=_layout([{"widget": "runs", "span": "s8"}]))
    service.reset = AsyncMock(return_value=None)
    return service


def _preset_service() -> MagicMock:
    service = MagicMock()
    service.list_for_user = AsyncMock(return_value=([], 0))
    service.create = AsyncMock(
        return_value=_preset("Monday review", [{"widget": "runs", "span": "s8", "rows": "r3"}])
    )
    service.delete = AsyncMock(return_value=None)
    return service


async def test_no_saved_layout_is_a_404() -> None:
    service = _service()
    async with _client(service) as client:
        resp = await client.get("/api/v1/me/dashboard-layout")
    assert resp.status_code == 404


async def test_a_saved_layout_is_returned() -> None:
    service = _service()
    service.get_for_user = AsyncMock(return_value=_layout([{"widget": "spend", "span": "s6"}]))
    async with _client(service) as client:
        resp = await client.get("/api/v1/me/dashboard-layout")
    assert resp.status_code == 200
    # An entry saved before heights, dividers or per-card settings existed reads
    # back with `rows`, `label`, `accent` and `options` null and `collapsed`
    # false, not a rejection - the read shape is permissive on purpose, and fills
    # the fields it predates.
    assert resp.json()["entries"] == [
        {
            "kind": "widget",
            "widget": "spend",
            "span": "s6",
            "rows": None,
            "label": None,
            "accent": None,
            "collapsed": False,
            "options": None,
        }
    ]


async def test_saving_an_arrangement_returns_it() -> None:
    service = _service()
    async with _client(service) as client:
        resp = await client.put(
            "/api/v1/me/dashboard-layout",
            json={"entries": [{"widget": "runs", "span": "s8"}]},
        )
    assert resp.status_code == 200
    assert service.save.call_args.kwargs["data"].entries[0].widget == "runs"


async def test_saving_an_empty_arrangement_is_accepted() -> None:
    service = _service()
    service.save = AsyncMock(return_value=_layout([]))
    async with _client(service) as client:
        resp = await client.put("/api/v1/me/dashboard-layout", json={"entries": []})
    assert resp.status_code == 200
    assert resp.json()["entries"] == []


async def test_saving_an_unknown_widget_is_refused_before_it_is_stored() -> None:
    service = _service()
    async with _client(service) as client:
        resp = await client.put(
            "/api/v1/me/dashboard-layout",
            json={"entries": [{"widget": "not-a-widget", "span": "s8"}]},
        )
    assert resp.status_code == 422
    service.save.assert_not_called()


async def test_saving_a_span_outside_the_closed_set_is_refused() -> None:
    service = _service()
    async with _client(service) as client:
        resp = await client.put(
            "/api/v1/me/dashboard-layout",
            json={"entries": [{"widget": "runs", "span": "s9"}]},
        )
    assert resp.status_code == 422
    service.save.assert_not_called()


async def test_resetting_answers_204_and_asks_the_service_to_reset() -> None:
    service = _service()
    async with _client(service) as client:
        resp = await client.delete("/api/v1/me/dashboard-layout")
    assert resp.status_code == 204
    service.reset.assert_awaited_once()


async def test_saving_a_height_outside_the_closed_set_is_refused() -> None:
    service = _service()
    async with _client(service) as client:
        resp = await client.put(
            "/api/v1/me/dashboard-layout",
            json={"entries": [{"widget": "runs", "span": "s8", "rows": "r9"}]},
        )
    assert resp.status_code == 422
    service.save.assert_not_called()


async def test_a_placement_height_travels_through_a_save() -> None:
    service = _service()
    service.save = AsyncMock(return_value=_layout([{"widget": "runs", "span": "s8", "rows": "r4"}]))
    async with _client(service) as client:
        resp = await client.put(
            "/api/v1/me/dashboard-layout",
            json={"entries": [{"widget": "runs", "span": "s8", "rows": "r4"}]},
        )
    assert resp.status_code == 200
    assert resp.json()["entries"] == [
        {
            "kind": "widget",
            "widget": "runs",
            "span": "s8",
            "rows": "r4",
            "label": None,
            "accent": None,
            "collapsed": False,
            "options": None,
        }
    ]


async def test_listing_presets_returns_them_with_a_total() -> None:
    presets = _preset_service()
    presets.list_for_user = AsyncMock(
        return_value=([_preset("Monday review", [{"widget": "runs", "span": "s8"}])], 1)
    )
    async with _client(_service(), presets) as client:
        resp = await client.get("/api/v1/me/dashboard-layout/presets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Monday review"


async def test_creating_a_preset_answers_201_with_the_row() -> None:
    presets = _preset_service()
    async with _client(_service(), presets) as client:
        resp = await client.post(
            "/api/v1/me/dashboard-layout/presets",
            json={"name": "Monday review", "entries": [{"widget": "runs", "span": "s8"}]},
        )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Monday review"
    assert presets.create.call_args.kwargs["data"].name == "Monday review"


async def test_creating_a_preset_with_an_unknown_widget_is_refused_at_the_boundary() -> None:
    presets = _preset_service()
    async with _client(_service(), presets) as client:
        resp = await client.post(
            "/api/v1/me/dashboard-layout/presets",
            json={"name": "ok", "entries": [{"widget": "not-a-widget", "span": "s8"}]},
        )
    assert resp.status_code == 422
    presets.create.assert_not_called()


async def test_a_duplicate_preset_name_is_a_409() -> None:
    presets = _preset_service()
    presets.create = AsyncMock(
        side_effect=AlreadyExistsError(
            message="A dashboard preset with this name already exists",
            details={"name": "Monday review"},
        )
    )
    async with _client(_service(), presets) as client:
        resp = await client.post(
            "/api/v1/me/dashboard-layout/presets",
            json={"name": "Monday review", "entries": []},
        )
    assert resp.status_code == 409


async def test_the_preset_cap_is_a_422() -> None:
    presets = _preset_service()
    presets.create = AsyncMock(
        side_effect=ValidationError(
            message="Dashboard preset limit reached — delete one to save another",
            details={"limit": MAX_PRESETS},
        )
    )
    async with _client(_service(), presets) as client:
        resp = await client.post(
            "/api/v1/me/dashboard-layout/presets", json={"name": "one too many", "entries": []}
        )
    assert resp.status_code == 422


async def test_deleting_a_preset_answers_204() -> None:
    presets = _preset_service()
    async with _client(_service(), presets) as client:
        resp = await client.delete(f"/api/v1/me/dashboard-layout/presets/{uuid4()}")
    assert resp.status_code == 204
    presets.delete.assert_awaited_once()


async def test_deleting_a_preset_outside_the_callers_scope_is_a_404() -> None:
    presets = _preset_service()
    presets.delete = AsyncMock(
        side_effect=NotFoundError(message="Dashboard preset not found", details={})
    )
    async with _client(_service(), presets) as client:
        resp = await client.delete(f"/api/v1/me/dashboard-layout/presets/{uuid4()}")
    assert resp.status_code == 404


async def test_a_cards_own_settings_travel_through_a_save() -> None:
    """A card's window, style and narrowing round-trip as one object.

    They are what makes one dashboard hold "the last 90 days for this agent"
    beside "this month, everything" - useless if the save drops them.
    """
    agent_id = str(uuid4())
    options = {"period": "90d", "style": "bars", "agent_id": agent_id, "user_id": None}
    service = _service()
    service.save = AsyncMock(
        return_value=_layout([{"widget": "runs", "span": "s8", "rows": "r4", "options": options}])
    )
    async with _client(service) as client:
        resp = await client.put(
            "/api/v1/me/dashboard-layout",
            json={"entries": [{"widget": "runs", "span": "s8", "rows": "r4", "options": options}]},
        )

    assert resp.status_code == 200
    assert resp.json()["entries"][0]["options"] == options
    saved = service.save.call_args.kwargs["data"].entries[0]
    assert saved.options is not None
    assert str(saved.options.agent_id) == agent_id


async def test_a_style_this_build_does_not_know_is_refused_at_the_boundary() -> None:
    # Same rule as an unknown widget id: a typo is a 422 where it is written,
    # not a card that silently draws the wrong chart forever.
    service = _service()
    async with _client(service) as client:
        resp = await client.put(
            "/api/v1/me/dashboard-layout",
            json={"entries": [{"widget": "runs", "span": "s8", "options": {"style": "sankey"}}]},
        )

    assert resp.status_code == 422
    service.save.assert_not_called()


async def test_a_window_outside_the_preset_set_is_refused() -> None:
    service = _service()
    async with _client(service) as client:
        resp = await client.put(
            "/api/v1/me/dashboard-layout",
            json={"entries": [{"widget": "runs", "span": "s8", "options": {"period": "5y"}}]},
        )

    assert resp.status_code == 422
    service.save.assert_not_called()
