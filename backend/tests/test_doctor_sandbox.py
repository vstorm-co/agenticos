"""`doctor`'s answer to "can this deployment give an agent a container?".

The probe checks the token as well as the address, and that is the part worth a
test. `/healthz` is unauthenticated by design, so a probe that stopped there
would report a healthy service to a deployment holding the wrong secret - and
every session would still be refused, inside a conversation, long after the
person who could fix it stopped looking.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.commands.doctor import _sandbox_service
from app.core import config as config_module

pytestmark = pytest.mark.anyio


class _Response:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._payload


class _Client:
    def __init__(self, health: _Response | Exception, policy: _Response | None = None) -> None:
        self._health = health
        self._policy = policy

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str] | None = None) -> _Response:
        if url.endswith("/healthz"):
            if isinstance(self._health, Exception):
                raise self._health
            return self._health
        assert self._policy is not None
        return self._policy


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(config_module.settings, "SANDBOXD_URL", "http://sandboxd:8080")
    monkeypatch.setattr(config_module.settings, "SANDBOXD_TOKEN", "service-token")


def _serve(monkeypatch, client: _Client) -> None:
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)


async def test_no_service_is_not_a_failure(monkeypatch):
    """A deployment running only the `state` backend is installed correctly."""
    monkeypatch.setattr(config_module.settings, "SANDBOXD_URL", "")

    status, detail = await _sandbox_service()

    assert status == "unconfigured"
    assert "state" in detail


async def test_a_named_service_that_does_not_answer_is_a_failure(monkeypatch, configured):
    """An agent asking for a container would fail on its first tool call."""
    _serve(monkeypatch, _Client(health=OSError("connection refused")))

    status, detail = await _sandbox_service()

    assert status == "unhealthy"
    assert "did not answer" in detail


async def test_the_wrong_token_is_reported_rather_than_looking_healthy(monkeypatch, configured):
    _serve(monkeypatch, _Client(health=_Response(200), policy=_Response(401)))

    status, detail = await _sandbox_service()

    assert status == "unhealthy"
    assert "SANDBOXD_TOKEN" in detail


async def test_any_other_refusal_is_reported_with_its_status(monkeypatch, configured):
    _serve(monkeypatch, _Client(health=_Response(200), policy=_Response(503)))

    status, detail = await _sandbox_service()

    assert status == "unhealthy"
    assert "503" in detail


async def test_a_service_allowing_no_runtime_cannot_start_a_sandbox(monkeypatch, configured):
    """It answers, it accepts the token, and it can do nothing."""
    _serve(monkeypatch, _Client(health=_Response(200), policy=_Response(200, {"runtimes": []})))

    status, detail = await _sandbox_service()

    assert status == "unhealthy"
    assert "no runtime" in detail


async def test_a_working_service_names_what_it_allows(monkeypatch, configured):
    """The aliases are what a spec may name, so an operator can compare them
    against what their agents actually ask for."""
    _serve(
        monkeypatch,
        _Client(
            health=_Response(200),
            policy=_Response(200, {"runtimes": [{"alias": "python"}, {"alias": "coding"}]}),
        ),
    )

    status, detail = await _sandbox_service()

    assert status == "healthy"
    assert "coding, python" in detail
