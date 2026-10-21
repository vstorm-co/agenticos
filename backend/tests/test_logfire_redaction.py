"""A request span must not carry a secret from the path out of the deployment.

With `LOGFIRE_TOKEN` set, every request becomes a span sent to Logfire, and the
ASGI instrumentation records the path and the full URL on it - keys Logfire's own
scrubber deliberately leaves alone. Logfire also attaches the endpoint's parsed
arguments. So a signed view token, a public link's key or a form's token left in
three places: the URL attributes, the arguments, and - when no route matched in
full - the span name.

And it left before the request ended: Logfire copies every span the moment it
starts into a pending span, which the console exporter prints to stdout and the
OTLP exporter can send on its own. So Logfire is configured here by
`setup_logfire` itself, console included, and the pending spans are read too.
The app is instrumented exactly as `create_app` instruments the real one.
"""

from __future__ import annotations

import contextlib
import json
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import logfire
import pytest
from fastapi import APIRouter, FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from logfire.testing import TestExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from app.core.logfire_setup import instrument_app, setup_logfire
from app.core.security import create_artifact_view_token

pytestmark = pytest.mark.anyio


@dataclass
class Captured:
    exporter: TestExporter
    capsys: pytest.CaptureFixture[str]

    def exported(self) -> str:
        """Every span the exporters were handed, the pending copies included."""
        return json.dumps(self.exporter.exported_spans_as_dict(_include_pending_spans=True))

    def console(self) -> str:
        """What the console exporter printed."""
        return self.capsys.readouterr().out


@pytest.fixture
def configured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Iterator[Captured]:
    """Logfire as `setup_logfire` configures it, plus an exporter to read.

    The exporter is appended after the processors `setup_logfire` passes, as a
    deployment's exporters come after them; nothing is sent anywhere, and the
    console writes to the stdout `capsys` captures.
    """
    exporter = TestExporter()
    configure = logfire.configure

    def with_exporter(**kwargs: Any) -> Any:
        processors = [*kwargs.pop("additional_span_processors"), SimpleSpanProcessor(exporter)]
        kwargs["send_to_logfire"] = False
        return configure(**kwargs, additional_span_processors=processors)

    monkeypatch.setattr(logfire, "configure", with_exporter)
    setup_logfire()
    capsys.readouterr()
    try:
        yield Captured(exporter=exporter, capsys=capsys)
    finally:
        # The console stays on otherwise, and prints every later test's spans.
        configure(send_to_logfire=False, console=False)


def _instrumented_app() -> FastAPI:
    router = APIRouter()

    @router.get("/artifact-content/{token}")
    async def content(token: str) -> dict[str, int]:
        return {"length": len(token)}

    @router.get("/public/artifacts/{public_key}")
    async def public(public_key: str) -> dict[str, int]:
        return {"length": len(public_key)}

    @router.get("/public/workflow-forms/{token}")
    async def form(token: str) -> dict[str, int]:
        return {"length": len(token)}

    @router.get("/workflows/{workflow_id}/webhook-test/{token}")
    async def webhook_test(workflow_id: str, token: str) -> dict[str, int]:
        return {"length": len(workflow_id + token)}

    @router.post("/workflow-resume/{run_id}/{token}")
    async def resume(run_id: UUID, token: str) -> dict[str, int]:
        return {"length": len(token)}

    @router.post("/invitations/{token}/accept")
    async def accept(token: str) -> dict[str, int]:
        return {"length": len(token)}

    @router.delete("/invitations/{token}")
    async def revoke(token: str) -> dict[str, int]:
        return {"length": len(token)}

    @router.get("/artifacts/{artifact_id}")
    async def member(artifact_id: str) -> dict[str, str]:
        return {"id": artifact_id}

    # The widget socket's signature: both credentials arrive in the query.
    @router.websocket("/embed/{public_key}/ws")
    async def embed_socket(
        websocket: WebSocket,
        public_key: str,
        token: str | None = Query(default=None),
        visitor: str | None = Query(default=None, max_length=64),
    ) -> None:
        await websocket.accept()
        await websocket.send_text(str(len(public_key)))
        await websocket.close()

    # The provider's return: authlib reads `code` and `state` off the request, so
    # neither is an argument.
    @router.get("/oauth/{provider}/callback")
    async def callback(provider: str, request: Request) -> dict[str, int]:
        return {"length": len(request.query_params.get("code") or "")}

    @router.get("/oauth/{provider}/login")
    async def login(
        provider: str,
        invitation_handle: str | None = None,
        client: str | None = None,
        desktop_nonce: str | None = None,
    ) -> dict[str, str]:
        return {"provider": provider}

    @router.get("/agents")
    async def search(q: str = "", skip: int = 0, limit: int = 50) -> dict[str, str]:
        return {"q": q}

    app = FastAPI()
    # Through `include_router`, as the real API is: it is what makes a wrong-method
    # request name its span after the raw path (`app/core/otel_compat.py`).
    app.include_router(router, prefix="/api/v1")
    instrument_app(app)
    return app


async def _request(*requests: tuple[str, str]) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_instrumented_app()), base_url="http://test"
    ) as client:
        for method, path in requests:
            await client.request(method, path)


@pytest.mark.security
async def test_no_span_carries_a_secret_from_the_path(configured: Captured) -> None:
    token = create_artifact_view_token(uuid4(), expires_in=timedelta(minutes=5))
    key, form_token = secrets.token_urlsafe(24), secrets.token_urlsafe(24)

    await _request(
        ("GET", f"/api/v1/artifact-content/{token}"),
        ("GET", f"/api/v1/public/artifacts/{key}?ref=mail"),
        ("POST", f"/api/v1/artifact-content/{token}"),
        ("GET", f"/api/v1/public/workflow-forms/{form_token}"),
    )

    exported = configured.exported()
    assert '"pending_span"' in exported, "the pending copies are part of what is read"
    for secret in (token, key, form_token):
        assert secret not in exported
    assert "/api/v1/artifact-content/[REDACTED]" in exported
    assert "/api/v1/public/artifacts/[REDACTED]?ref=mail" in exported
    assert "/api/v1/public/workflow-forms/[REDACTED]" in exported


@pytest.mark.security
async def test_the_console_does_not_print_a_secret_from_the_path(configured: Captured) -> None:
    """The console exporter is on by default and prints the pending span to stdout,
    where no logging filter runs."""
    token = create_artifact_view_token(uuid4(), expires_in=timedelta(minutes=5))

    await _request(("GET", f"/api/v1/artifact-content/{token}"))

    printed = configured.console()
    assert token not in printed
    assert "GET /api/v1/artifact-content/[REDACTED]" in printed


@pytest.mark.security
async def test_a_path_parameter_that_is_not_the_secret_keeps_its_value(
    configured: Captured,
) -> None:
    """The workflow's id before `/webhook-test/<token>` names the workflow; only the
    token is the credential, in the path and in the arguments."""
    workflow_id, token = str(uuid4()), secrets.token_urlsafe(32)

    await _request(("GET", f"/api/v1/workflows/{workflow_id}/webhook-test/{token}"))

    exported = configured.exported()
    assert token not in exported
    assert f"/api/v1/workflows/{workflow_id}/webhook-test/[REDACTED]" in exported
    assert _arguments(configured) == [{"workflow_id": workflow_id, "token": "[REDACTED]"}]


def _arguments(configured: Captured) -> list[dict[str, str]]:
    """The endpoint arguments Logfire attached to each finished request span."""
    return [
        json.loads(span["attributes"]["fastapi.arguments.values"])
        for span in configured.exporter.exported_spans_as_dict()
        if "fastapi.arguments.values" in span["attributes"]
    ]


@pytest.mark.security
async def test_a_resume_link_keeps_its_run_and_loses_its_token(configured: Captured) -> None:
    """The resume token is the HMAC that wakes the run's Wait steps; the run id
    before it is not a credential and names the run being resumed."""
    run_id, token = str(uuid4()), secrets.token_hex(32)

    await _request(("POST", f"/api/v1/workflow-resume/{run_id}/{token}"))

    exported = configured.exported()
    assert token not in exported
    assert f"/api/v1/workflow-resume/{run_id}/[REDACTED]" in exported
    assert _arguments(configured) == [{"run_id": run_id, "token": "[REDACTED]"}]


@pytest.mark.security
async def test_no_span_carries_an_invitation_token(configured: Captured) -> None:
    """The invitee's accept and revoke routes take the token in the path."""
    token = secrets.token_urlsafe(32)

    await _request(
        ("POST", f"/api/v1/invitations/{token}/accept"),
        ("DELETE", f"/api/v1/invitations/{token}"),
    )

    exported = configured.exported()
    assert token not in exported
    assert "/api/v1/invitations/[REDACTED]/accept" in exported
    assert _arguments(configured) == [{"token": "[REDACTED]"}, {"token": "[REDACTED]"}]


async def test_a_route_with_nothing_secret_in_its_path_keeps_its_arguments(
    configured: Captured,
) -> None:
    """The arguments are what makes a span worth reading; only a secret-bearing
    address gives them up."""
    artifact_id = str(uuid4())

    await _request(("GET", f"/api/v1/artifacts/{artifact_id}"))

    exported = configured.exported()
    assert exported.count(artifact_id) >= 2, "both the URL and the argument keep the id"
    assert "[REDACTED]" not in exported


@pytest.mark.security
async def test_the_widget_socket_s_query_credentials_reach_no_span(configured: Captured) -> None:
    """`?visitor=` resumes a hosted page's conversation and `?token=` is the
    customer's signed visitor token; the socket's span carried both in
    `http.target`, `http.url` and `url.query`, on the pending copy and the final
    span alike, and in the endpoint's arguments."""
    key, visitor = "pk_live_widget", secrets.token_hex(16)
    token = create_artifact_view_token(uuid4(), expires_in=timedelta(minutes=5))

    with (
        TestClient(_instrumented_app()) as client,
        client.websocket_connect(f"/api/v1/embed/{key}/ws?visitor={visitor}&token={token}") as ws,
    ):
        ws.receive_text()

    exported = configured.exported()
    spans = configured.exporter.exported_spans_as_dict(_include_pending_spans=True)
    socket = {
        span["attributes"]["logfire.span_type"]: span["attributes"]["http.url"]
        for span in spans
        if "/embed/" in span["attributes"].get("http.url", "")
    }
    redacted = f"ws://testserver/api/v1/embed/{key}/ws?visitor=[REDACTED]&token=[REDACTED]"
    assert socket == {"pending_span": redacted, "span": redacted}
    assert visitor not in exported and token not in exported
    assert _arguments(configured) == [
        {"public_key": key, "token": "[REDACTED]", "visitor": "[REDACTED]"}
    ]
    assert visitor not in configured.console() and token not in configured.console()


@pytest.mark.security
async def test_a_credential_that_fails_validation_reaches_no_span(configured: Captured) -> None:
    """A `visitor` past its 64 characters is refused, and Logfire records the refusal
    with the rejected value as the error's `input`."""
    visitor = secrets.token_hex(40)

    with (
        TestClient(_instrumented_app()) as client,
        contextlib.suppress(WebSocketDisconnect),
        client.websocket_connect(f"/api/v1/embed/pk_live_widget/ws?visitor={visitor}") as ws,
    ):
        ws.receive_text()

    errors = [
        span["attributes"]["fastapi.arguments.errors"]
        for span in configured.exporter.exported_spans_as_dict()
        if "fastapi.arguments.errors" in span["attributes"]
    ]
    assert errors, "the refusal was not recorded, so this test proves nothing"
    assert visitor not in configured.exported() and visitor not in configured.console()
    assert "[REDACTED]" in errors[0]


@pytest.mark.security
async def test_a_sign_in_s_return_keeps_its_code_and_state_out_of_the_span(
    configured: Captured,
) -> None:
    """The provider sends the browser back with its authorization code and the
    CSRF state in the query; neither is an argument, so the URL is where they were."""
    code, state = secrets.token_urlsafe(32), secrets.token_urlsafe(32)

    await _request(("GET", f"/api/v1/oauth/google/callback?state={state}&code={code}&scope=openid"))

    exported = configured.exported()
    assert code not in exported and state not in exported
    assert "/api/v1/oauth/google/callback?state=[REDACTED]&code=[REDACTED]&scope=openid" in exported
    assert _arguments(configured) == [{"provider": "google"}]


@pytest.mark.security
async def test_an_invitation_handle_is_masked_and_the_rest_of_a_sign_in_kept(
    configured: Captured,
) -> None:
    """The handle redeems the invitation it stands in for; `client` and the desktop
    nonce admit nothing and say which flow this was."""
    handle, nonce = secrets.token_urlsafe(32), secrets.token_hex(16)

    await _request(
        (
            "GET",
            f"/api/v1/oauth/oidc/login?invitation_handle={handle}&client=desktop&desktop_nonce={nonce}",
        )
    )

    exported = configured.exported()
    assert handle not in exported
    assert f"invitation_handle=[REDACTED]&client=desktop&desktop_nonce={nonce}" in exported
    assert _arguments(configured) == [
        {
            "provider": "oidc",
            "invitation_handle": "[REDACTED]",
            "client": "desktop",
            "desktop_nonce": nonce,
        }
    ]


async def test_ordinary_query_parameters_keep_their_values(configured: Captured) -> None:
    """A search, a page and an id in the query are what a span is read for."""
    await _request(("GET", "/api/v1/agents?q=support&skip=50&limit=25"))

    exported = configured.exported()
    assert "/api/v1/agents?q=support&skip=50&limit=25" in exported
    assert "[REDACTED]" not in exported
    assert _arguments(configured) == [{"q": "support", "skip": 50, "limit": 25}]
