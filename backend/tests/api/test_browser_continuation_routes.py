"""Continuation HTTP routes expose fixed receipts and never execute a browser effect."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.browser_continuation import (
    BrowserContinuationReason,
    BrowserContinuationRefused,
    BrowserContinuationState,
)
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.browser_credential_continuation import BrowserCredentialContinuationRead
from tests.test_browser_session import ORIGIN, PRIVATE

pytestmark = [pytest.mark.anyio, pytest.mark.security]
RUN, SUBMIT, FILL, PLAN, SECRET, GENERATION, DOCUMENT, ORG, USER = (uuid4() for _ in range(9))
BASE = f"{settings.API_V1_STR}/runs/{RUN}/browser-credential-plans/{SUBMIT}/continuation"


def receipt(state=BrowserContinuationState.REQUESTED):
    return BrowserCredentialContinuationRead(
        id=PLAN,
        organization_id=ORG,
        user_id=USER,
        run_id=RUN,
        source_submission_id=SUBMIT,
        source_fill_id=FILL,
        source_call_id="source-call",
        source_tab_id="source-tab",
        secret_id=SECRET,
        authorization_generation=GENERATION,
        state=state,
        origin=ORIGIN,
        document_id=DOCUMENT,
        expires_at=datetime.now(UTC) + timedelta(seconds=60),
        keep_signed_in=False,
        saved_sign_in_id=None,
        continuation_call_id=None,
        continuation_tab_id=None,
        reason_code=None,
        output_protected=True,
    )


@pytest.fixture
def service():
    return SimpleNamespace(
        get=AsyncMock(return_value=None),
        request=AsyncMock(return_value=receipt()),
        confirm=AsyncMock(return_value=receipt(BrowserContinuationState.APPROVED)),
    )


@pytest.fixture
async def client(service, mock_redis):
    ctx = AuthContext(user_id=USER, organization_id=ORG, role="owner")
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_browser_credential_continuation_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened
    finally:
        app.dependency_overrides.clear()


def confirmation():
    return {
        "document_id": str(DOCUMENT),
        "authorization_generation": str(GENERATION),
        "approve": True,
        "keep_signed_in": False,
    }


async def test_typed_prepare_and_exact_consent_delegate_only_to_durable_service(client, service):
    prepared = await client.post(BASE, json={"request_id": str(PLAN)})
    decided = await client.post(BASE + f"/{PLAN}/confirmation", json=confirmation())
    assert prepared.status_code == 202 and decided.status_code == 200
    for response in (prepared, decided):
        assert "no-store" in response.headers["cache-control"]
        assert response.json()["output_protected"] is True and PRIVATE not in response.text
    assert service.request.await_args.args[1:3] == (RUN, SUBMIT)
    assert service.request.await_args.args[3].request_id == PLAN
    assert service.confirm.await_args.args[1:4] == (RUN, SUBMIT, PLAN)
    assert service.confirm.await_args.args[4].keep_signed_in is False


@pytest.mark.parametrize("state", [None, *BrowserContinuationState])
async def test_get_recovery_never_prepares_or_confirms_any_effect(client, service, state):
    found = None if state is None else receipt(state)
    service.get.return_value = found
    response = await client.get(BASE)
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    assert response.json() == (None if found is None else found.model_dump(mode="json"))
    service.get.assert_awaited_once()
    service.request.assert_not_awaited()
    service.confirm.assert_not_awaited()


@pytest.mark.parametrize("stage", ["prepare", "confirm"])
@pytest.mark.parametrize(
    "field", ["cookies", "local_storage", "url", "script", "password", "source_call_id"]
)
async def test_page_values_and_destination_overrides_are_rejected_without_echo(
    client, service, caplog, stage, field
):
    payload = {"request_id": str(PLAN)} if stage == "prepare" else confirmation()
    payload[field] = PRIVATE
    target = BASE if stage == "prepare" else BASE + f"/{PLAN}/confirmation"
    response = await client.post(target, json=payload)
    assert response.status_code == 422 and PRIVATE not in response.text + caplog.text
    service.request.assert_not_awaited()
    service.confirm.assert_not_awaited()


async def test_persistence_choice_cannot_be_omitted(client, service):
    payload = confirmation()
    del payload["keep_signed_in"]
    response = await client.post(BASE + f"/{PLAN}/confirmation", json=payload)
    assert response.status_code == 422
    service.confirm.assert_not_awaited()


async def test_refusal_metadata_is_fixed_and_owner_failures_remain_opaque(client, service):
    service.request.side_effect = BrowserContinuationRefused(
        BrowserContinuationReason.OWNERSHIP_LOST
    )
    refused = await client.post(BASE, json={"request_id": str(PLAN)})
    assert refused.status_code == 400
    assert refused.json()["error"]["details"] == {"reason_code": "browser_ownership_lost"}
    service.get.side_effect = NotFoundError(message="Browser submission not found")
    assert (await client.get(BASE)).status_code == 404
