"""`doctor`'s answer to "can this deployment give an agent a container?".

Two things here are worth a test rather than a reading.

The probe checks the credential as well as the address. `/healthz` is
unauthenticated by design, so a probe that stopped there would report a healthy
service to a deployment holding the wrong secret - and every session would still
be refused, inside a conversation, long after the person who could fix it stopped
looking.

And it probes *every* registered connection, not one address. That is the whole
point of the connections table: an organization may run two hosts and a
deployment hosts many organizations, so a summary that stopped at the first
healthy one would hide the broken second.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.commands.doctor import _probe_connection, _sandbox_connections
from app.core.secret_kinds import ApiKeySecret, AwsCredentialsSecret, seal_secret
from app.core.vault import VaultScope

pytestmark = pytest.mark.anyio

ORG_ID = uuid.uuid4()


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


def _serve(monkeypatch, client: _Client) -> None:
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)


def _connection(*, name: str = "Local Docker", base_url: str = "http://sandboxd:8080") -> MagicMock:
    row = MagicMock()
    row.name = name
    row.base_url = base_url
    row.organization_id = ORG_ID
    return row


def _secret(value: Any = None) -> MagicMock:
    """A vault row sealed for `ORG_ID`, so the probe unseals it for real."""
    value = value or ApiKeySecret(api_key="service-token")
    sealed = seal_secret(value, scope=VaultScope.organization(ORG_ID))
    row = MagicMock()
    row.kind = value.kind.value
    row.sealed_secret = sealed.ciphertext
    row.key_version = sealed.key_version
    return row


def _db(rows: list[tuple[Any, Any]]) -> MagicMock:
    db = MagicMock()
    result = MagicMock()
    result.tuples.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db


async def test_no_connection_registered_is_not_a_failure():
    """A deployment running only the `state` backend is installed correctly."""
    status, detail = await _sandbox_connections(_db([]))

    assert status == "unconfigured"
    assert "state" in detail


async def test_a_registered_service_that_does_not_answer_is_a_failure(monkeypatch):
    """An agent bound to it would fail on its first tool call."""
    _serve(monkeypatch, _Client(health=OSError("connection refused")))

    status, detail = await _sandbox_connections(_db([(_connection(), _secret())]))

    assert status == "unhealthy"
    assert "did not answer" in detail


async def test_every_connection_is_named_not_just_the_first(monkeypatch):
    """A summary that stopped at the healthy one would hide the broken one."""
    _serve(monkeypatch, _Client(health=OSError("connection refused")))
    rows = [
        (_connection(name="Big box"), _secret()),
        (_connection(name="Little box"), _secret()),
    ]

    status, detail = await _sandbox_connections(_db(rows))

    assert status == "unhealthy"
    assert "Big box" in detail
    assert "Little box" in detail


async def test_a_working_service_counts_what_answered(monkeypatch):
    _serve(
        monkeypatch,
        _Client(health=_Response(200), policy=_Response(200, {"runtimes": [{"alias": "python"}]})),
    )

    status, detail = await _sandbox_connections(_db([(_connection(), _secret())]))

    assert status == "healthy"
    assert "1 connection" in detail


async def test_a_connection_whose_credential_was_deleted_says_so():
    """`SET NULL` on the vault reference makes this reachable, and it is the one
    failure a network probe cannot describe."""
    assert await _probe_connection(_connection(), None) == (
        "no credential in the vault - re-attach one"
    )


async def test_the_wrong_kind_of_credential_is_reported_rather_than_sent(monkeypatch):
    """A sandbox service authenticates with a token; AWS keys are not one, and
    handing them over would be a credential sent to the wrong host."""
    secret = _secret(
        AwsCredentialsSecret(
            aws_access_key_id="AKIA0000", aws_secret_access_key="x", region_name="eu-west-1"
        )
    )

    detail = await _probe_connection(_connection(), secret)

    assert detail is not None
    assert "cannot authenticate" in detail


async def test_a_credential_sealed_for_another_organization_is_reported(monkeypatch):
    """The scope is the organization, so a row moved between tenants unseals to
    nothing - and the operator needs to be told that, not "did not answer"."""
    connection = _connection()
    connection.organization_id = uuid.uuid4()

    detail = await _probe_connection(connection, _secret())

    assert detail is not None
    assert "could not be unsealed" in detail


async def test_the_wrong_token_is_reported_rather_than_looking_healthy(monkeypatch):
    _serve(monkeypatch, _Client(health=_Response(200), policy=_Response(401)))

    detail = await _probe_connection(_connection(), _secret())

    assert detail == "the service answered but refused its credential"


async def test_any_other_refusal_is_reported_with_its_status(monkeypatch):
    _serve(monkeypatch, _Client(health=_Response(200), policy=_Response(503)))

    detail = await _probe_connection(_connection(), _secret())

    assert detail is not None
    assert "503" in detail


async def test_a_service_allowing_no_runtime_cannot_start_a_sandbox(monkeypatch):
    """It answers, it accepts the token, and it can do nothing."""
    _serve(monkeypatch, _Client(health=_Response(200), policy=_Response(200, {"runtimes": []})))

    detail = await _probe_connection(_connection(), _secret())

    assert detail == "the service allows no runtime, so no sandbox can start"
