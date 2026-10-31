"""Diagnostics signs a closed protocol and never makes reporting a user dependency."""

import base64
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.vault import VaultScope, seal
from app.db.models.diagnostics import DiagnosticsIdentity
from app.repositories import diagnostics as repo
from app.schemas.diagnostics import PresenceCreate, SignedError, SignedHeartbeat, SignedRegistration
from app.services.diagnostics import DiagnosticsService, usage_bucket
from app.services.diagnostics.identity import Identity
from app.worker.jobs import Tick
from app.worker.tasks.diagnostics_tasks import send_diagnostics

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 10, 31, 12, 15, tzinfo=UTC)


def row() -> DiagnosticsIdentity:
    secret = seal(base64.b64encode(b"a" * 32).decode(), scope=VaultScope.deployment())
    return DiagnosticsIdentity(
        id=1, sealed_seed=secret.ciphertext, secret_key_version=secret.key_version
    )


@pytest.fixture
def diagnostic_repo(monkeypatch):
    state = row()
    monkeypatch.setattr(settings, "DIAGNOSTICS_ENABLED", True)
    monkeypatch.setattr(settings, "DIAGNOSTICS_COLLECTOR_URL", "http://localhost:8010")
    monkeypatch.setattr(settings, "DIAGNOSTICS_PUBLIC_URL", "http://localhost:8010")
    for name, value in {
        "get": state,
        "initialize": state,
        "save": None,
        "worker_alive": True,
        "feature_counts": {"chat": 12, "voice": 0},
        "failures": [("agents", "run_failed", 1234)],
    }.items():
        monkeypatch.setattr(repo, name, AsyncMock(return_value=value))
    return state


@pytest.mark.parametrize(
    "count,expected",
    [
        (0, "0"),
        (1, "1-9"),
        (9, "1-9"),
        (10, "10-99"),
        (99, "10-99"),
        (100, "100-999"),
        (999, "100-999"),
        (1000, "1000+"),
    ],
)
def test_usage_is_bucketed(count, expected):
    assert usage_bucket(count) == expected


def test_missing_env_keeps_diagnostics_enabled_and_explicit_false_disables(monkeypatch):
    monkeypatch.delenv("DIAGNOSTICS_ENABLED", raising=False)
    assert Settings(_env_file=None).DIAGNOSTICS_ENABLED is True
    monkeypatch.setenv("DIAGNOSTICS_ENABLED", "false")
    assert Settings(_env_file=None).DIAGNOSTICS_ENABLED is False


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:pass@example.com",
        "https://example.com/path",
        "https://example.com?token=secret",
        "https://example.com#fragment",
        "javascript:alert(1)",
    ],
)
def test_collector_configuration_refuses_credentials_paths_and_unencrypted_remote_hosts(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DIAGNOSTICS_COLLECTOR_URL=url)


def test_local_and_https_origins_are_normalized():
    config = Settings(
        _env_file=None,
        DIAGNOSTICS_COLLECTOR_URL="http://host.docker.internal:8010/",
        DIAGNOSTICS_PUBLIC_URL="https://analytics.example.com/",
    )
    assert config.DIAGNOSTICS_COLLECTOR_URL == "http://host.docker.internal:8010"
    assert config.DIAGNOSTICS_PUBLIC_URL == "https://analytics.example.com"


def test_identity_is_stable_per_installation_and_unlinkable_across_installations():
    user = uuid4()
    first, same, other = Identity(b"a" * 32), Identity(b"a" * 32), Identity(b"b" * 32)
    assert first.user_id(user) == same.user_id(user)
    assert first.instance_id == same.instance_id
    assert first.user_id(user) != other.user_id(user)
    assert first.user_id(user) != first.user_id(uuid4())
    assert user.hex not in first.user_id(user)
    assert "seed" not in repr(first)
    assert first.event_id("heartbeat:1") != first.event_id("heartbeat:2")


async def test_disabled_means_no_database_reads_signatures_or_network(monkeypatch, mock_db_session):
    monkeypatch.setattr(settings, "DIAGNOSTICS_ENABLED", False)
    get = AsyncMock(side_effect=AssertionError("disabled diagnostics accessed DB"))
    monkeypatch.setattr(repo, "get", get)
    service = DiagnosticsService(mock_db_session)
    assert await service.send() == "disabled"
    assert await service.presence(user_id=uuid4(), surface="web") is None
    assert await send_diagnostics(Tick(scheduled_for=NOW)) == "disabled"
    get.assert_not_called()


def verify(envelope: dict, public_key: str) -> None:
    Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key)).verify(
        base64.b64decode(envelope["signature"]),
        json.dumps(envelope["payload"], sort_keys=True, separators=(",", ":")).encode(),
    )


async def test_heartbeat_and_error_contracts_are_signed_and_do_not_contain_raw_content(
    diagnostic_repo, mock_db_session
):
    seen = []

    def collect(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert not request.headers.get("authorization")
        assert not request.headers.get("cookie")
        return httpx.Response(200, json={"accepted": True, "duplicate": False})

    service = DiagnosticsService(mock_db_session)
    assert await service.send(transport=httpx.MockTransport(collect), now=NOW) == "sent"
    assert [item["payload"]["kind"] for item in seen] == ["registration", "heartbeat", "error"]
    SignedRegistration.model_validate(seen[0])
    SignedHeartbeat.model_validate(seen[1])
    SignedError.model_validate(seen[2])
    for item in seen:
        verify(item, seen[0]["payload"]["public_key"])
    assert seen[2]["payload"]["count"] == 1000
    assert seen[1]["payload"]["features"] == [
        {"name": "chat", "enabled": True, "usage": "10-99"},
        {"name": "voice", "enabled": False, "usage": "0"},
    ]
    assert diagnostic_repo.last_success == NOW
    assert await service.send(now=NOW + timedelta(minutes=1)) == "already_sent"
    state = await service.status()
    assert state.enabled and state.last_success == int(NOW.timestamp())
    assert "sealed_seed" not in state.model_dump()


async def test_first_send_initializes_once_and_a_busy_replica_skips(
    diagnostic_repo, monkeypatch, mock_db_session
):
    monkeypatch.setattr(repo, "get", AsyncMock(side_effect=[None, diagnostic_repo]))
    monkeypatch.setattr(repo, "failures", AsyncMock(return_value=[]))
    monkeypatch.setattr(repo, "worker_alive", AsyncMock(return_value=False))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"accepted": True}))
    service = DiagnosticsService(mock_db_session)
    await service.initialize()
    assert await service.send(transport=transport, now=NOW) == "sent"
    assert repo.initialize.await_count == 1
    monkeypatch.setattr(repo, "get", AsyncMock(return_value=None))
    assert await DiagnosticsService(mock_db_session).send(now=NOW) == "busy"


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (503, {}, "rejected"),
        (200, {"accepted": False}, "rejected"),
        (200, {"accepted": True, "unexpected": "sensitive"}, "rejected"),
        (200, "x" * 5000, "rejected"),
    ],
)
async def test_rejection_is_visible_without_exposing_upstream_content(
    diagnostic_repo, mock_db_session, status, body, expected
):
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    service = DiagnosticsService(mock_db_session)
    assert await service.send(transport=transport, now=NOW) == expected
    assert diagnostic_repo.last_success is None
    assert (await service.status()).last_error == expected


async def test_transport_outage_does_not_break_the_worker_or_log_sensitive_urls(
    diagnostic_repo, mock_db_session
):
    def fail(request):
        raise httpx.ConnectError("secret upstream detail", request=request)

    service = DiagnosticsService(mock_db_session)
    assert await service.send(transport=httpx.MockTransport(fail), now=NOW) == "transport"
    assert (await service.status()).last_error == "transport"


async def test_presence_is_bound_to_authenticated_user_and_expires_in_a_minute(
    diagnostic_repo, mock_db_session
):
    service = DiagnosticsService(mock_db_session)
    user = uuid4()
    assert await service.presence(user_id=user, surface="desktop") is None
    diagnostic_repo.last_success = NOW
    claim = await service.presence(user_id=user, surface="desktop")
    assert claim is not None
    assert claim.event.payload.expires_at - claim.event.payload.at == 60
    assert claim.event.payload.user_id == Identity(b"a" * 32).user_id(user)
    verify(claim.event.model_dump(mode="json"), Identity(b"a" * 32).public_key)
    assert str(user) not in claim.model_dump_json()
    with pytest.raises(ValidationError):
        PresenceCreate.model_validate({"surface": "web", "user_id": str(user)})


async def test_no_identity_does_not_create_one_from_presence_or_status(
    monkeypatch, mock_db_session
):
    monkeypatch.setattr(repo, "get", AsyncMock(return_value=None))
    service = DiagnosticsService(mock_db_session)
    assert await service.presence(user_id=uuid4(), surface="mobile") is None
    assert (await service.status()).instance_id is None


async def test_initialization_is_idempotent_when_identity_already_exists(
    diagnostic_repo, mock_db_session
):
    await DiagnosticsService(mock_db_session).initialize()
    repo.initialize.assert_not_awaited()


async def test_hourly_job_commits_identity_before_sending(monkeypatch, mock_db_session):
    from contextlib import asynccontextmanager

    from app.worker.tasks import diagnostics_tasks

    events = []

    @asynccontextmanager
    async def session():
        events.append("open")
        yield mock_db_session
        events.append("commit")

    async def initialize(self):
        events.append("initialize")

    async def send(self):
        events.append("send")
        return "sent"

    monkeypatch.setattr(settings, "DIAGNOSTICS_ENABLED", True)
    monkeypatch.setattr(diagnostics_tasks, "get_db_context", session)
    monkeypatch.setattr(DiagnosticsService, "initialize", initialize)
    monkeypatch.setattr(DiagnosticsService, "send", send)
    assert await send_diagnostics(Tick(scheduled_for=NOW)) == "sent"
    assert events == ["open", "initialize", "commit", "open", "send", "commit"]
