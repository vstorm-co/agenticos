"""HTTP teaching transitions require revision preconditions and never accept capture events."""

from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import Auth, BrowserTeachingDraftSvc, BrowserTeachingPolicySvc, BrowserTeachingSvc
from app.api.routes.v1 import browser_teaching as routes
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.schemas.browser_teaching import TeachingList, TeachingPolicyRead, TeachingPreferenceRead
from tests.test_browser_teaching_capture import receipt
from tests.test_browser_teaching_contracts import ORIGIN, SECRET
from tests.test_browser_teaching_native import identity

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
async def api():
    held = identity()
    ctx = AuthContext(user_id=held.user_id, organization_id=held.organization_id, role="owner")
    data = receipt(held)
    service = SimpleNamespace(
        **{
            name: AsyncMock(return_value=data)
            for name in ("start", "get", "change", "stop", "discard", "propose")
        }
    )
    service.list = AsyncMock(return_value=TeachingList(items=(), next_cursor=None))
    policy = TeachingPolicyRead(enabled=False, generation=None, deployment_enabled=True)
    preference = TeachingPreferenceRead(
        agent_id=held.agent_id, enabled=False, generation=None, allowed=True
    )
    policies = SimpleNamespace(
        get=AsyncMock(return_value=policy),
        update=AsyncMock(return_value=policy),
        preference=AsyncMock(return_value=preference),
        update_preference=AsyncMock(return_value=preference),
    )
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_args(Auth)[1].dependency] = lambda: ctx
    for alias in (BrowserTeachingSvc, BrowserTeachingDraftSvc):
        app.dependency_overrides[get_args(alias)[1].dependency] = lambda: service
    app.dependency_overrides[get_args(BrowserTeachingPolicySvc)[1].dependency] = lambda: policies
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield SimpleNamespace(
            client=client,
            held=held,
            context=ctx,
            data=data,
            service=service,
            policies=policies,
        )


def start_body(a):
    return {
        "request_id": str(a.data.id),
        "run_id": str(a.held.run_id),
        "call_id": a.held.call_id,
        "tab_id": a.held.tab_id,
        "takeover_id": str(a.held.takeover_id),
        "title": "Synthetic procedure",
        "allowed_origins": [ORIGIN],
    }


async def test_owner_collection_passes_only_the_bounded_page_arguments(api):
    response = await api.client.get("/browser-teachings")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"items": [], "next_cursor": None}
    api.service.list.assert_awaited_once_with(api.context, limit=20, cursor=None)
    api.service.list.reset_mock()
    response = await api.client.get("/browser-teachings", params={"limit": 100, "cursor": "opaque"})
    assert response.status_code == 200
    api.service.list.assert_awaited_once_with(api.context, limit=100, cursor="opaque")


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"limit": "x"}, {"cursor": "x" * 513}]
)
async def test_unbounded_owner_pages_are_refused_before_the_service(api, params):
    response = await api.client.get("/browser-teachings", params=params)
    assert response.status_code == 422
    api.service.list.assert_not_awaited()


@pytest.mark.parametrize("skill", [False, True])
async def test_start_returns_owner_metadata_and_exact_revision_without_cache(api, skill):
    a = api
    skill_id = uuid4()
    response = await a.client.post(
        f"/skills/{skill_id}/browser-teachings" if skill else "/browser-teachings",
        json=start_body(a),
    )
    assert response.status_code == 201
    assert response.headers["etag"] == '"1"' and response.headers["cache-control"] == "no-store"
    assert response.json()["id"] == str(a.data.id)
    if skill:
        assert a.service.start.call_args.kwargs == {"skill_id": skill_id}
    assert SECRET not in response.text


@pytest.mark.parametrize(
    ("method", "suffix", "body", "target", "code"),
    [
        ("GET", "", None, "get", 200),
        ("PATCH", "", {"action": "pause"}, "change", 200),
        ("POST", "/stop", None, "stop", 200),
        ("DELETE", "", None, "discard", 200),
        ("POST", "/propose", {"mode": "reviewed"}, "propose", 202),
    ],
)
async def test_owner_transition_carries_the_original_context_and_revision(
    api, method, suffix, body, target, code
):
    a = api
    response = await a.client.request(
        method,
        f"/browser-teachings/{a.data.id}{suffix}",
        json=body,
        headers={"If-Match": '"1"'},
    )
    assert response.status_code == code and response.headers["etag"] == '"1"'
    assert response.headers["cache-control"] == "no-store"
    called = getattr(a.service, target)
    assert called.call_args.args[:2] == (a.context, a.data.id)
    if target in {"change", "propose"}:
        assert called.call_args.args[2] == 1


@pytest.mark.parametrize("value", ["0", "-1", "W/1", "*", '"0"', '"1', "1,2", "1\n", "10000000000"])
async def test_invalid_revision_never_reaches_a_write(value):
    with pytest.raises(BadRequestError):
        routes._revision(value)


@pytest.mark.parametrize("value", ["1", '"1"', "9999999999"])
async def test_revision_accepts_only_the_bounded_exact_integer(value):
    assert routes._revision(value) == int(value.strip('"'))


async def test_missing_revision_and_client_supplied_capture_events_are_refused(api):
    a = api
    response = await a.client.patch(f"/browser-teachings/{a.data.id}", json={"action": "pause"})
    assert response.status_code == 422
    a.service.change.assert_not_awaited()
    response = await a.client.post(
        "/browser-teachings", json={**start_body(a), "events": [{"text": SECRET}]}
    )
    assert response.status_code == 422
    a.service.start.assert_not_awaited()
    response = await a.client.post(f"/browser-teachings/{a.data.id}/events", json={"text": SECRET})
    assert response.status_code == 404


@pytest.mark.parametrize("method", ["GET", "PUT"])
async def test_policy_and_member_choice_are_separate_scoped_requests(api, method):
    a = api
    body = {"enabled": False, "generation": None} if method == "PUT" else None
    response = await a.client.request(method, "/browser-teaching-policy", json=body)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    response = await a.client.request(
        method, f"/agents/{a.held.agent_id}/browser-teaching-preference", json=body
    )
    assert response.status_code == 200 and not response.json()["enabled"]
    target = a.policies.update_preference if method == "PUT" else a.policies.preference
    assert target.call_args.args[:2] == (a.context, a.held.agent_id)
