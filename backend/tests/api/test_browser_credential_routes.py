"""Owner-scoped browser APIs expose IDs and reviewed metadata, never a native writer."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.browser_fill import (
    BrowserFillOperation,
    BrowserFillReason,
    BrowserFillRefused,
    BrowserFillState,
)
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.browser_credential import (
    BrowserCredentialEligible,
    BrowserCredentialPlanRead,
    BrowserCredentialPolicyRead,
)
from app.schemas.secret import BrowserSecretMetadata
from tests.test_browser_credentials import PASSWORD, SEED, USERNAME, login

pytestmark = [pytest.mark.anyio, pytest.mark.security]
RUN, PLAN, SECRET, GENERATION, DOCUMENT = (uuid4() for _ in range(5))
BASE = f"{settings.API_V1_STR}/runs/{RUN}"


def plan(state=BrowserFillState.REQUESTED, operation=BrowserFillOperation.FILL):
    return BrowserCredentialPlanRead(
        id=PLAN,
        operation=operation,
        parent_plan_id=None,
        run_id=RUN,
        call_id="call",
        tab_id="main",
        secret_id=SECRET,
        authorization_generation=GENERATION,
        state=state,
        fields=["password"],
        origin="https://portal.example.test",
        document_id=DOCUMENT,
        expires_at=datetime.now(UTC) + timedelta(seconds=60),
        reason_code=None,
        output_protected=False,
    )


@pytest.fixture
def services():
    plans = SimpleNamespace(
        eligible=AsyncMock(
            return_value=[
                BrowserCredentialEligible(
                    id=SECRET,
                    name="Synthetic portal",
                    kind="browser_login",
                    authorization_generation=GENERATION,
                    usage_scope="personal",
                    browser=BrowserSecretMetadata.from_secret(login()),
                )
            ]
        ),
        request=AsyncMock(return_value=plan()),
        get=AsyncMock(return_value=plan()),
        confirm=AsyncMock(return_value=plan(BrowserFillState.APPROVED)),
        submit=AsyncMock(return_value=plan(BrowserFillState.APPROVED, BrowserFillOperation.SUBMIT)),
        submitted=AsyncMock(return_value=None),
    )
    policy = BrowserCredentialPolicyRead(
        secret_id=SECRET,
        authorization_generation=GENERATION,
        mode="personal",
        agent_ids=[],
        member_ids=[],
    )
    return SimpleNamespace(
        plans=plans,
        policy=SimpleNamespace(
            get=AsyncMock(return_value=policy), update=AsyncMock(return_value=policy)
        ),
    )


@pytest.fixture
async def client(services, mock_redis) -> AsyncIterator[AsyncClient]:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_browser_credential_plan_service] = lambda: services.plans
    app.dependency_overrides[deps.get_browser_credential_policy_service] = lambda: services.policy
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened
    finally:
        app.dependency_overrides.clear()


def request():
    return {
        "request_id": str(uuid4()),
        "secret_id": str(SECRET),
        "authorization_generation": str(GENERATION),
        "call_id": "call",
        "tab_id": "main",
        "fields": [{"field": "password", "element_id": 0}],
    }


async def test_route_contracts_are_typed_uncached_and_leave_effects_to_the_native_owner(
    client, services
) -> None:
    responses = [
        await client.get(
            BASE + "/browser-credentials", params={"call_id": "call", "tab_id": "main"}
        ),
        await client.post(BASE + "/browser-credential-plans", json=request()),
        await client.get(BASE + f"/browser-credential-plans/{PLAN}"),
        await client.post(
            BASE + f"/browser-credential-plans/{PLAN}/confirmation",
            json={
                "document_id": str(DOCUMENT),
                "authorization_generation": str(GENERATION),
                "approve": True,
            },
        ),
        await client.post(
            BASE + f"/browser-credential-plans/{PLAN}/submission",
            json={
                "request_id": str(uuid4()),
                "document_id": str(DOCUMENT),
                "authorization_generation": str(GENERATION),
            },
        ),
        await client.get(f"{settings.API_V1_STR}/secrets/{SECRET}/browser-policy"),
        await client.put(
            f"{settings.API_V1_STR}/secrets/{SECRET}/browser-policy",
            json={
                "generation": str(GENERATION),
                "mode": "personal",
                "agent_ids": [],
                "member_ids": [],
            },
        ),
    ]
    assert [response.status_code for response in responses] == [200, 202, 200, 200, 202, 200, 200]
    for response in responses:
        assert "no-store" in response.headers["cache-control"]
        assert not any(
            value in response.text for value in (PASSWORD, SEED, USERNAME, "sealed_secret")
        )
    services.plans.eligible.assert_awaited_once()
    services.plans.request.assert_awaited_once()
    services.plans.confirm.assert_awaited_once()
    services.plans.submit.assert_awaited_once()
    assert services.plans.request.await_args.args[2].fields[0].element_id == 0
    assert services.plans.confirm.await_args.args[3].approve is True


@pytest.mark.parametrize("extra", ["password", "selector", "script", "url"])
async def test_fill_api_refuses_values_selectors_scripts_and_destinations_without_echo(
    client, services, caplog, extra
) -> None:
    payload = request()
    payload[extra] = PASSWORD
    response = await client.post(BASE + "/browser-credential-plans", json=payload)
    assert response.status_code == 422
    assert PASSWORD not in response.text + caplog.text
    services.plans.request.assert_not_awaited()


async def test_bad_field_and_stale_controller_refusal_have_only_fixed_reason(
    client, services, caplog
) -> None:
    payload = request()
    payload["fields"][0]["field"] = PASSWORD
    response = await client.post(BASE + "/browser-credential-plans", json=payload)
    assert response.status_code == 422 and PASSWORD not in response.text + caplog.text
    services.plans.request.side_effect = BrowserFillRefused(BrowserFillReason.LIVE_BROWSER_REQUIRED)
    refused = await client.post(BASE + "/browser-credential-plans", json=request())
    assert refused.status_code == 400
    assert refused.json()["error"]["details"] == {"reason_code": "live_browser_required"}
    services.plans.get.side_effect = NotFoundError(message="Browser credential plan not found")
    assert (await client.get(BASE + f"/browser-credential-plans/{PLAN}")).status_code == 404


async def test_policy_has_no_implicit_shared_audience(client, services) -> None:
    response = await client.put(
        f"{settings.API_V1_STR}/secrets/{SECRET}/browser-policy",
        json={
            "generation": str(GENERATION),
            "mode": "shared",
            "agent_ids": [],
            "member_ids": [],
        },
    )
    assert response.status_code == 422
    services.policy.update.assert_not_awaited()


@pytest.mark.parametrize(
    "state",
    [
        None,
        BrowserFillState.APPROVED,
        BrowserFillState.CLAIMED,
        BrowserFillState.SUBMITTED,
        BrowserFillState.UNKNOWN,
    ],
)
async def test_submission_recovery_reads_only_the_existing_attempt(client, services, state):
    receipt = None if state is None else plan(state, BrowserFillOperation.SUBMIT)
    services.plans.submitted.return_value = receipt
    response = await client.get(BASE + f"/browser-credential-plans/{PLAN}/submission")
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    assert response.json() == (None if receipt is None else receipt.model_dump(mode="json"))
    assert services.plans.submitted.await_args.args[1:] == (RUN, PLAN)
    services.plans.request.assert_not_awaited()
    services.plans.confirm.assert_not_awaited()
    services.plans.submit.assert_not_awaited()


async def test_submission_recovery_cannot_bypass_parent_ownership(client, services):
    services.plans.submitted.side_effect = NotFoundError(
        message="Browser credential plan not found"
    )
    response = await client.get(BASE + f"/browser-credential-plans/{PLAN}/submission")
    assert response.status_code == 404
    services.plans.submit.assert_not_awaited()
