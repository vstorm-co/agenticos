"""Health endpoint tests."""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.core.config import settings


@pytest.mark.anyio
async def test_health_check(client: AsyncClient):
    """Test liveness probe."""
    response = await client.get(f"{settings.API_V1_STR}/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.anyio
async def test_readiness_check(client: AsyncClient):
    """Test readiness probe with mocked dependencies."""
    response = await client.get(f"{settings.API_V1_STR}/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["ready", "degraded"]
    assert "checks" in data


@pytest.mark.anyio
async def test_readiness_check_redis_healthy(client: AsyncClient, mock_redis):
    """Test readiness when Redis is healthy."""
    mock_redis.ping = AsyncMock(return_value=True)

    response = await client.get(f"{settings.API_V1_STR}/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["checks"]["redis"]["status"] == "healthy"
    assert "latency_ms" in data["checks"]["redis"]


@pytest.mark.anyio
async def test_readiness_check_redis_unhealthy(client: AsyncClient, mock_redis):
    """Test readiness when Redis is unhealthy."""
    mock_redis.ping = AsyncMock(side_effect=Exception("Connection failed"))

    response = await client.get(f"{settings.API_V1_STR}/ready")
    # Should return 503 when Redis is down
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["checks"]["redis"]["status"] == "unhealthy"


@pytest.mark.anyio
async def test_readiness_check_db_healthy(client: AsyncClient, mock_db_session):
    """Test readiness when database is healthy."""
    # Mock successful DB query
    mock_db_session.execute = AsyncMock()

    response = await client.get(f"{settings.API_V1_STR}/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["checks"]["database"]["status"] == "healthy"


@pytest.mark.anyio
async def test_readiness_check_db_unhealthy(client: AsyncClient, mock_db_session):
    """Test readiness when database is unhealthy."""
    mock_db_session.execute = AsyncMock(side_effect=Exception("DB connection failed"))

    response = await client.get(f"{settings.API_V1_STR}/ready")
    # Should return 503 when DB is down
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["checks"]["database"]["status"] == "unhealthy"


@pytest.mark.anyio
async def test_liveness_probe_reports_the_build(client: AsyncClient):
    """The liveness probe answers about the process, and consults nothing."""
    response = await client.get(f"{settings.API_V1_STR}/health/live")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"
    assert data["details"]["environment"] == settings.ENVIRONMENT


@pytest.mark.anyio
async def test_the_readiness_payload_reports_only_what_gates_traffic(client: AsyncClient):
    """No vector store, no LLM provider, no Stripe.

    Every one of those was on this payload, and none of them could take a pod out
    of rotation - they were there because the admin page read its data from a
    Kubernetes probe. Two audiences, two endpoints: the operator's view is
    ``/admin/system``, which authenticates.
    """
    response = await client.get(f"{settings.API_V1_STR}/health/ready")

    assert response.status_code == 200
    data = response.json()
    assert set(data["checks"]) == {"database", "redis"}
    # The flattened copy the admin page used to read is gone with it.
    assert "database" not in data


@pytest.mark.anyio
async def test_a_failing_readiness_probe_does_not_describe_the_network(
    client: AsyncClient, mock_db_session
):
    """This endpoint takes no credential, so a driver error must not reach it.

    "connection to server at 10.0.1.7, port 5432 failed: password authentication
    failed for user postgres" is three facts about the deployment handed to
    anyone who can reach the port. The reason belongs in the log.
    """
    mock_db_session.execute = AsyncMock(
        side_effect=Exception("connection to server at 10.0.1.7 failed for user postgres")
    )

    response = await client.get(f"{settings.API_V1_STR}/health/ready")

    assert response.status_code == 503
    assert "10.0.1.7" not in response.text
    assert "postgres" not in response.text
