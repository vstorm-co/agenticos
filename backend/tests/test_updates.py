"""Local update protocol refuses privileged operations and preserves drain state."""

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConfigurationError
from app.core.update_gate import UpdateInProgress, draining, require_admission
from app.schemas.updates import UpdateApply, UpdateCancel, UpdatePrepare
from app.services.updates import UpdateService

pytestmark = pytest.mark.anyio


def test_gate_is_opt_in_and_unreadable_or_active_flags_refuse_new_work(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPDATE_AGENT_SOCKET", None)
    assert not draining()
    require_admission()
    monkeypatch.setattr(settings, "UPDATE_AGENT_SOCKET", tmp_path / "agent.sock")
    assert draining()
    control = tmp_path / "control.json"
    for value in ({"draining": True}, {}, [False]):
        control.write_text(json.dumps(value))
        assert draining()
        with pytest.raises(UpdateInProgress):
            require_admission()
    control.write_text("malformed")
    assert draining()
    control.write_text('{"draining":false}')
    assert not draining()
    require_admission()


async def test_unconfigured_updater_reports_setup_and_never_connects(monkeypatch):
    monkeypatch.setattr(settings, "UPDATE_AGENT_SOCKET", None)
    monkeypatch.setattr(
        settings, "UPDATE_PIPELINE_URL", "https://github.com/company/platform/actions"
    )
    status = await UpdateService().status()
    assert not status.configured and not status.reachable and status.operation is None
    assert status.pipeline_url == "https://github.com/company/platform/actions"
    with pytest.raises(ConfigurationError):
        await UpdateService().prepare(UpdatePrepare(version="1.33.0"), actor_user_id=uuid4())


async def test_transport_passes_only_validated_operations_and_the_authenticated_actor(monkeypatch):
    monkeypatch.setattr(settings, "UPDATE_AGENT_SOCKET", Path("/run/agenticos-updater/agent.sock"))
    requests = []

    def serve(request):
        requests.append(request)
        return httpx.Response(200, json={"operation": None})

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(serve))
    service, actor = UpdateService(), uuid4()
    assert (await service.status()).reachable
    await service.prepare(UpdatePrepare(version="1.33.0"), actor_user_id=actor)
    await service.apply(UpdateApply(id="a" * 32), actor_user_id=actor)
    await service.cancel(UpdateCancel(id="a" * 32), actor_user_id=actor)
    assert [request.url.path for request in requests] == [
        "/v1/status",
        "/v1/prepare",
        "/v1/apply",
        "/v1/cancel",
    ]
    assert json.loads(requests[1].content) == {"version": "1.33.0", "actor_id": str(actor)}
    assert all(
        not request.headers.get("authorization") and not request.headers.get("cookie")
        for request in requests
    )


@pytest.mark.parametrize(
    "status,body,error",
    [
        (409, {}, BadRequestError),
        (503, {}, ConfigurationError),
        (200, {"operation": None, "secret": "must-not-leak"}, ConfigurationError),
        (200, "x" * 20000, ConfigurationError),
    ],
)
async def test_invalid_or_refused_agent_responses_do_not_leak_contents(
    monkeypatch, status, body, error
):
    monkeypatch.setattr(settings, "UPDATE_AGENT_SOCKET", Path("/run/updater.sock"))
    monkeypatch.setattr(
        httpx,
        "AsyncHTTPTransport",
        lambda **kwargs: httpx.MockTransport(lambda req: httpx.Response(status, json=body)),
    )
    with pytest.raises(error) as caught:
        await UpdateService().prepare(UpdatePrepare(version="1.33.0"), actor_user_id=uuid4())
    assert "must-not-leak" not in str(caught.value)
    if error is ConfigurationError:
        assert not (await UpdateService().status()).reachable


async def test_network_outage_is_an_explicit_unreachable_state(monkeypatch):
    monkeypatch.setattr(settings, "UPDATE_AGENT_SOCKET", Path("/run/updater.sock"))

    def fail(request):
        raise httpx.ConnectError("private socket error", request=request)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(fail))
    status = await UpdateService().status()
    assert status.configured and not status.reachable
