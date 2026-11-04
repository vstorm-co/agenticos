"""A `sandboxd` of another version is reported as one, not as a lost session (#2484).

The client reads every 404 on a session route as "the session is gone", and a
service that lacks the route answers with FastAPI's bare 404. These hold the line
between the two: only that body, confirmed by the service's own index, becomes a
version mismatch, and the compose files run the version the client speaks.
"""

import logging
import re
import tomllib
from pathlib import Path

import httpx
import pytest
from pydantic_ai.workspaces import WorkspaceUnavailableError

from app.commands.sandbox_runtimes import COMPOSE_FILES
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
    pinned = {name: pattern.findall((REPO_ROOT / name).read_text()) for name in COMPOSE_FILES}

    assert pinned == {name: [SANDBOXD_VERSION] for name in COMPOSE_FILES}


def test_the_licence_inventory_names_the_version_the_compose_files_run():
    """The inventory feeds the notices and the release SBOM, so a bump that moved
    only the compose files would ship a record of an image nothing runs."""
    inventory = tomllib.loads((REPO_ROOT / "licenses" / "components.toml").read_text())
    [entry] = [c for c in inventory["component"] if c["name"] == SANDBOXD_IMAGE]

    assert entry["version"] == SANDBOXD_VERSION


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

    async def test_no_index_at_all_is_an_error_not_a_version(self):
        """Every published sandboxd has an index, so a 404 at `/` is something in
        front of it - a path-routing proxy - and says nothing about the routes."""
        client, _ = _client(httpx.Response(404, json={"detail": "Not Found"}))

        with pytest.raises(httpx.HTTPStatusError):
            await missing_endpoints(client, BASE)

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

    async def test_a_route_the_service_lacks_is_a_version_mismatch(
        self, caplog: pytest.LogCaptureFixture
    ):
        client, _ = _client(_index(OLD_ENDPOINTS))

        with caplog.at_level(logging.WARNING, logger="app.services.sandboxd_compat"):
            explained = await explain_unavailable(
                WorkspaceUnavailableError(ROUTE_GONE), base_url=f"{BASE}/", client=client
            )

        assert isinstance(explained, SandboxdVersionMismatchError)
        # Still fails the call as an unavailable workspace does, and is the
        # operator's to fix.
        assert isinstance(explained, WorkspaceUnavailableError)
        assert isinstance(explained, ConfigurationError)
        assert explained.message == (
            "The sandbox service does not serve /sessions/{session_id}/run, "
            "/sessions/{session_id}/runs/{run_id}/stop - its version does not match "
            f"this platform (expected {SANDBOXD_VERSION}). Run "
            f"{SANDBOXD_IMAGE}:{SANDBOXD_VERSION} and redeploy it"
        )
        assert explained.details == {
            "missing": [
                "/sessions/{session_id}/run",
                "/sessions/{session_id}/runs/{run_id}/stop",
            ],
            "expected": SANDBOXD_VERSION,
        }
        assert "is gone" not in str(explained)
        # A run's error and a tool result are read by members and the model; the
        # address is the operator's, in the log (#342).
        assert BASE not in str(explained)
        [record] = [r for r in caplog.records if r.message == "sandboxd_version_mismatch"]
        assert record.__dict__["base_url"] == f"{BASE}/"

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


async def test_a_legacy_saved_session_conflict_reports_the_service_mismatch() -> None:
    client, asked = _client(_index(OLD_ENDPOINTS))
    request = httpx.Request("POST", f"{BASE}/sessions")
    response = httpx.Response(409, request=request, json={"detail": "Session exists"})
    error = httpx.HTTPStatusError("Session exists", request=request, response=response)

    explained = await explain_unavailable(error, base_url=BASE, client=client)

    assert isinstance(explained, SandboxdVersionMismatchError)
    assert asked == [f"{BASE}/"]


@pytest.mark.parametrize(
    "status,method,path",
    [
        (409, "POST", "/sessions"),
        (400, "POST", "/sessions"),
        (409, "GET", "/sessions"),
        (409, "POST", "/sessions/x/run"),
    ],
)
async def test_http_errors_are_not_relabelled_without_an_incompatible_index(
    status: int, method: str, path: str
) -> None:
    client, _ = _client(_index(list(REQUIRED_ENDPOINTS)))
    request = httpx.Request(method, f"{BASE}{path}")
    response = httpx.Response(status, request=request)
    error = httpx.HTTPStatusError("Conflict", request=request, response=response)
    assert await explain_unavailable(error, base_url=BASE, client=client) is None


async def test_an_ordinary_operation_error_never_probes_the_service() -> None:
    client, asked = _client(_index(OLD_ENDPOINTS))
    assert await explain_unavailable(RuntimeError("failed"), base_url=BASE, client=client) is None
    assert asked == []
