"""The binding-request routes: who may decide them, and what a deferred binding answers (#2076)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.channel_binding_request import BindingDeferred, ChannelBindingRequestRead

pytestmark = pytest.mark.anyio

_V1 = settings.API_V1_STR


def _request(**changes: object) -> ChannelBindingRequestRead:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "channel_bot_id": uuid.uuid4(),
        "agent_id": uuid.uuid4(),
        "exposure_id": None,
        "environment_id": None,
        "kind": "bind",
        "requester_user_id": uuid.uuid4(),
        "note": "Before Monday",
        "status": "pending",
        "void_reason": None,
        "decided_by_user_id": None,
        "decided_at": None,
        "created_at": datetime.now(UTC),
        "agent_name": "Support",
        "channel_bot_name": "Shop line",
        "requester_email": "ana@example.com",
    }
    return ChannelBindingRequestRead(**{**values, **changes})


async def _call(
    role: str, method: str, path: str, *, json: dict | None = None
) -> tuple[int, dict, AsyncMock, AsyncMock]:
    requests = AsyncMock()
    request = _request()
    requests.list_pending.return_value = ([request], 1)
    requests.list_for_agent.return_value = [request]
    requests.approve.return_value = request
    requests.decline.return_value = request
    exposures = AsyncMock()
    exposures.create.return_value = BindingDeferred(request_id=request.id, waiting_for="Ana Admin")
    exposures.update.return_value = BindingDeferred(request_id=request.id, waiting_for=None)
    app.dependency_overrides[deps.get_channel_binding_request_service] = lambda: requests
    app.dependency_overrides[deps.get_agent_exposure_service] = lambda: exposures
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
            answer = await http.request(method, f"{_V1}{path}", json=json)
    finally:
        app.dependency_overrides.clear()
    return answer.status_code, answer.json(), requests, exposures


_ID = uuid.uuid4()
_CHANNEL_ROUTES = [
    ("GET", "/channels/binding-requests"),
    ("POST", f"/channels/binding-requests/{_ID}/approve"),
    ("POST", f"/channels/binding-requests/{_ID}/decline"),
]


@pytest.mark.security
@pytest.mark.parametrize(("method", "path"), _CHANNEL_ROUTES)
async def test_a_builder_is_refused_on_the_channel_routes(method: str, path: str) -> None:
    status, _, requests, _ = await _call(OrgRoleName.BUILDER, method, path)

    assert status == 403
    for call in (requests.list_pending, requests.approve, requests.decline):
        call.assert_not_awaited()


async def test_an_owner_lists_approves_and_declines() -> None:
    status, body, requests, _ = await _call(OrgRoleName.OWNER, "GET", "/channels/binding-requests")
    assert status == 200
    assert body["total"] == 1 and body["items"][0]["note"] == "Before Monday"
    item = body["items"][0]
    assert (item["agent_name"], item["channel_bot_name"], item["requester_email"]) == (
        "Support",
        "Shop line",
        "ana@example.com",
    )
    requests.list_pending.assert_awaited_once()

    status, body, requests, _ = await _call(
        OrgRoleName.OWNER, "POST", f"/channels/binding-requests/{_ID}/approve"
    )
    assert status == 200 and body["status"] == "pending"
    requests.approve.assert_awaited_once()

    status, _, requests, _ = await _call(
        OrgRoleName.OWNER, "POST", f"/channels/binding-requests/{_ID}/decline"
    )
    assert status == 200
    requests.decline.assert_awaited_once()


async def test_a_deferred_binding_answers_202_with_the_request() -> None:
    status, body, _, exposures = await _call(
        OrgRoleName.BUILDER,
        "POST",
        f"/agents/{uuid.uuid4()}/exposures",
        json={"channel_bot_id": str(uuid.uuid4()), "request_note": "Please"},
    )

    assert status == 202
    assert set(body) == {"status", "request_id", "waiting_for"}
    assert body["status"] == "requested" and body["waiting_for"] == "Ana Admin"
    exposures.create.assert_awaited_once()


async def test_a_deferred_change_answers_202() -> None:
    status, body, _, _ = await _call(
        OrgRoleName.BUILDER,
        "PATCH",
        f"/agents/{uuid.uuid4()}/exposures/{uuid.uuid4()}",
        json={"is_active": True},
    )

    assert status == 202 and body["waiting_for"] is None


async def test_a_member_lists_the_requests_for_an_agent() -> None:
    status, body, requests, _ = await _call(
        OrgRoleName.BUILDER, "GET", f"/agents/{uuid.uuid4()}/binding-requests"
    )

    assert status == 200 and body["total"] == 1
    requests.list_for_agent.assert_awaited_once()


@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_a_note_past_500_characters_is_refused(method: str) -> None:
    path = f"/agents/{uuid.uuid4()}/exposures" + ("" if method == "POST" else f"/{uuid.uuid4()}")
    body = {"channel_bot_id": str(uuid.uuid4())} if method == "POST" else {"is_active": True}

    status, _, _, exposures = await _call(
        OrgRoleName.OWNER, method, path, json={**body, "request_note": "x" * 501}
    )

    assert status == 422
    exposures.create.assert_not_awaited()
    exposures.update.assert_not_awaited()


async def test_a_created_binding_answers_201() -> None:
    from unittest.mock import MagicMock

    from app.schemas.agent_exposure import ExposureRead

    bot_id = uuid.uuid4()
    read = ExposureRead(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        surface="whatsapp",
        channel_bot_id=bot_id,
        channel_bot_name="Front desk",
        is_active=True,
    )
    exposures = AsyncMock()
    exposures.create.return_value = MagicMock()
    exposures.list_for_agent.return_value = [read]
    app.dependency_overrides[deps.get_agent_exposure_service] = lambda: exposures
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
            answer = await http.post(
                f"{_V1}/agents/{uuid.uuid4()}/exposures", json={"channel_bot_id": str(bot_id)}
            )
    finally:
        app.dependency_overrides.clear()

    assert answer.status_code == 201
    assert answer.json()["channel_bot_id"] == str(bot_id)
