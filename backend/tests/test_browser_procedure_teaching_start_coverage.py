"""A person who already has a procedure recording open on this browser cannot start another."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.browser_procedure_teaching import BrowserProcedureTeachingReason
from app.core.exceptions import ConflictError
from app.core.permissions import AuthContext
from app.schemas.browser_procedure_teaching import BrowserProcedureTeachingStart
from app.services.browser_procedure_teaching import _service
from tests.test_browser_credential_lease import identity

pytestmark = pytest.mark.anyio


async def test_a_controller_with_an_open_recording_refuses_a_second_start(monkeypatch) -> None:
    native = identity()
    ctx = AuthContext(user_id=native.user_id, organization_id=native.organization_id, role="owner")
    data = BrowserProcedureTeachingStart(
        request_id=uuid4(),
        run_id=native.run_id,
        call_id=native.call_id,
        tab_id=native.tab_id,
        takeover_id=uuid4(),
        title="Synthetic procedure",
        allowed_origins=("https://portal.example.test",),
    )
    live = native.model_copy(update={"takeover_id": data.takeover_id})
    monkeypatch.setattr(_service._access, "person", AsyncMock(return_value=ctx))
    monkeypatch.setattr(_service._access, "admit", AsyncMock())
    monkeypatch.setattr(_service._access, "target", AsyncMock())
    monkeypatch.setattr(_service, "discover", AsyncMock(return_value=live))
    monkeypatch.setattr(_service.repo, "session", AsyncMock(return_value=None))
    monkeypatch.setattr(_service.repo, "policy", AsyncMock())
    monkeypatch.setattr(_service.repo, "active", AsyncMock(return_value=SimpleNamespace()))
    count = AsyncMock()
    monkeypatch.setattr(_service.repo, "owner_open_count", count)
    monkeypatch.setattr(
        _service.browser_teaching_view, "lock_view_and_check_active", AsyncMock(return_value=False)
    )
    service = _service.BrowserProcedureTeachingService(AsyncMock(), AsyncMock())
    with pytest.raises(ConflictError) as refused:
        await service.start(ctx, data)
    assert refused.value.details == {
        "reason_code": BrowserProcedureTeachingReason.ALREADY_ACTIVE.value
    }
    count.assert_not_awaited()
