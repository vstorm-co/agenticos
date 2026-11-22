"""A fill request is refused while a protected continuation already holds the page."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.browser_fill import BrowserFillReason, BrowserFillRefused
from app.core.permissions import AuthContext
from app.schemas.browser_credential import BrowserCredentialRequest
from app.services.browser_credentials import _plans
from tests.test_browser_credential_lease import identity

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_a_fill_request_is_refused_while_a_continuation_holds_the_page(monkeypatch) -> None:
    native = identity()
    ctx = AuthContext(user_id=native.user_id, organization_id=native.organization_id, role="owner")
    request = BrowserCredentialRequest(
        request_id=uuid4(),
        secret_id=native.credential_ids[0],
        authorization_generation=uuid4(),
        call_id=native.call_id,
        tab_id=native.tab_id,
        fields=[{"field": "password", "element_id": 0}],
    )
    service = _plans.BrowserCredentialPlanService(AsyncMock(), AsyncMock())
    monkeypatch.setattr(service, "live", AsyncMock(return_value=(ctx, native)))
    monkeypatch.setattr(_plans.repo, "lock_run", AsyncMock())
    monkeypatch.setattr(_plans.repo, "plan", AsyncMock(return_value=None))
    active = AsyncMock(return_value=object())
    monkeypatch.setattr(_plans.continuation_repo, "active_for_view", active)
    claimed = AsyncMock()
    monkeypatch.setattr(_plans.repo, "active_for_view", claimed)
    monkeypatch.setattr(_plans._access, "credential", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(_plans._access, "open_value", lambda secret: SimpleNamespace())
    monkeypatch.setattr(
        _plans.BrowserSecretMetadata,
        "from_secret",
        lambda value: SimpleNamespace(available_fields=["username", "password"]),
    )
    with pytest.raises(BrowserFillRefused) as refused:
        await service.request(ctx, native.run_id, request)
    assert refused.value.reason == BrowserFillReason.ALREADY_CONSUMED
    claimed.assert_not_awaited()
