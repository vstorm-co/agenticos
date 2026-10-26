"""A `sandboxd` of another version is reported as one, not as a lost session (#2484).

The client reads every 404 on a session route as "the session is gone", and a
service that lacks the route answers with FastAPI's bare 404. These hold the line
between the two: only that body, confirmed by the service's own index, becomes a
version mismatch, and the compose files run the version the client speaks.
"""

import re
from pathlib import Path

import httpx
import pytest
from pydantic_ai.workspaces import WorkspaceUnavailableError

from app.core.exceptions import ConfigurationError
from app.services.sandboxd_compat import (
    REQUIRED_ENDPOINTS,
    SANDBOXD_IMAGE,
    SANDBOXD_VERSION,
    SandboxdVersionMismatchError,
    explain_unavailable,
    missing_endpoints,
)

pytestmark = pytest.mark.anyio

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = "http://sandboxd:8080"

# What `/` answers on sandboxd 0.2.29, the image that broke a laptop: `/exec`
# rather than `/run`, and no way to stop a run.
OLD_ENDPOINTS = [
    "/healthz",
    "/policy",
    "/sessions",
    "/sessions/{session_id}",
    "/sessions/{session_id}/exec",
    "/sessions/{session_id}/read",
]
ROUTE_GONE = 'sandboxd session \'xc-1\' is gone: {"detail":"Not Found"}'


def _client(index: httpx.Response | Exception) -> tuple[httpx.AsyncClient, list[str]]:
    """A client whose only server is an index, and the URLs it was asked for."""
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        if isinstance(index, Exception):
            raise index
        return index

    return httpx.AsyncClient(transport=httpx.MockTransport(handle)), asked


def _index(endpoints: list[str]) -> httpx.Response:
    return httpx.Response(200, json={"service": "sandboxd", "endpoints": endpoints})


def test_every_compose_file_runs_the_version_the_client_speaks():
    """The pair moves together: bump `pydantic-ai-backend` and this names each
    compose file still running the old service."""
    pattern = re.compile(rf"image: {re.escape(SANDBOXD_IMAGE)}:(\S+)")
    pinned = {
        path.name: pattern.findall(path.read_text())
        for path in sorted(REPO_ROOT.glob("docker-compose*.yml"))
        if SANDBOXD_IMAGE in path.read_text()
    }

    assert pinned, "no compose file runs sandboxd"
    assert pinned == {name: [SANDBOXD_VERSION] for name in pinned}


class TestMissingEndpoints:
    async def test_a_matching_service_lacks_nothing(self):
        client, asked = _client(_index([*REQUIRED_ENDPOINTS, "/healthz"]))

        assert await missing_endpoints(client, f"{BASE}/") == []
        assert asked == [f"{BASE}/"]

    async def test_an_older_service_lacks_the_routes_it_never_had(self):
        client, _ = _client(_index(OLD_ENDPOINTS))

        assert await missing_endpoints(client, BASE) == [
            "/sessions/{session_id}/run",
            "/sessions/{session_id}/runs/{run_id}/stop",
        ]

    async def test_a_service_with_no_index_serves_none_of_them(self):
        client, _ = _client(httpx.Response(404, json={"detail": "Not Found"}))

        assert await missing_endpoints(client, BASE) == list(REQUIRED_ENDPOINTS)

    async def test_a_failing_service_is_an_error_not_an_answer(self):
        client, _ = _client(httpx.Response(503))

        with pytest.raises(httpx.HTTPStatusError):
            await missing_endpoints(client, BASE)

    async def test_something_that_is_not_an_index_is_refused(self):
        client, _ = _client(httpx.Response(200, json={"status": "ok"}))

        with pytest.raises(ValueError, match="endpoints"):
            await missing_endpoints(client, BASE)


class TestExplainingASessionFoundGone:
    async def test_the_services_own_404_is_believed_without_asking(self):
        """`No such session` is the service saying so; nothing else is fetched."""
        client, asked = _client(_index(OLD_ENDPOINTS))
        error = WorkspaceUnavailableError(
            'sandboxd session \'xc-1\' is gone: {"detail":"No such session: xc-1"}'
        )

        assert await explain_unavailable(error, base_url=BASE, client=client) is None
        assert asked == []

    async def test_a_route_the_service_lacks_is_a_version_mismatch(self):
        client, _ = _client(_index(OLD_ENDPOINTS))

        explained = await explain_unavailable(
            WorkspaceUnavailableError(ROUTE_GONE), base_url=f"{BASE}/", client=client
        )

        assert isinstance(explained, SandboxdVersionMismatchError)
        # Still ends the run as an unavailable workspace does, and is the
        # operator's to fix.
        assert isinstance(explained, WorkspaceUnavailableError)
        assert isinstance(explained, ConfigurationError)
        assert explained.message == (
            f"sandboxd at {BASE} does not serve /sessions/{{session_id}}/run, "
            f"/sessions/{{session_id}}/runs/{{run_id}}/stop - its version does not match "
            f"this platform (expected {SANDBOXD_VERSION}). Run "
            f"{SANDBOXD_IMAGE}:{SANDBOXD_VERSION} (`docker compose pull sandboxd` and recreate it)"
        )
        assert explained.details == {
            "base_url": f"{BASE}/",
            "missing": [
                "/sessions/{session_id}/run",
                "/sessions/{session_id}/runs/{run_id}/stop",
            ],
            "expected": SANDBOXD_VERSION,
        }
        assert "is gone" not in str(explained)

    async def test_a_service_serving_every_route_leaves_the_error_alone(self):
        """A bare 404 from a proxy in front of a matching service is not a version."""
        client, _ = _client(_index(list(REQUIRED_ENDPOINTS)))

        error = WorkspaceUnavailableError(ROUTE_GONE)

        assert await explain_unavailable(error, base_url=BASE, client=client) is None

    @pytest.mark.parametrize(
        "index",
        [httpx.ConnectError("refused"), httpx.Response(200, json={"status": "ok"})],
        ids=["unreachable", "not-an-index"],
    )
    async def test_an_index_that_cannot_settle_it_leaves_the_error_alone(
        self, index: httpx.Response | Exception
    ):
        client, _ = _client(index)

        error = WorkspaceUnavailableError(ROUTE_GONE)

        assert await explain_unavailable(error, base_url=BASE, client=client) is None
