"""`http.request` in a real run: SSRF, credential origins, redaction, limits (#1789).

The network is replaced at the transport - what would have gone on the wire is
recorded - and DNS is stubbed, so the SSRF check and the pinning run for real
against addresses the test chooses. Secrets are real vault rows: sealed,
stored and opened the way a deployment does it.
"""

from __future__ import annotations

import base64
import socket
import uuid
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.pinned_http import PinnedAsyncClient
from app.core.secret_kinds import ApiKeySecret, HttpCredentialSecret, seal_secret
from app.core.vault import VaultScope
from app.db.models.organization import Organization
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.workflow_run import NodeAttempt, NodeRun, WorkflowRunStatus
from app.workflows.contracts.io import Binding, LiteralValue, NodeOutputRef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from app.workflows.nodes.http_request import _handler as http_handler
from tests.integration.workflow_run_support import SeededRun, drive, seed_member, seed_run

pytestmark = pytest.mark.anyio

_PUBLIC = "93.184.216.34"
_TOKEN = "tok-abcdef-123456"


class _Wire(httpx2.AsyncBaseTransport):
    """The network, replaced: records every request and answers with `responder`."""

    def __init__(self, responder: Callable[[httpx2.Request], httpx2.Response]) -> None:
        self.responder = responder
        self.sent: list[httpx2.Request] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        await request.aread()
        self.sent.append(request)
        return self.responder(request)


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> Callable[..., _Wire]:
    """Install a wire and a DNS stub; returns a function that sets the responder."""
    wire = _Wire(lambda _r: httpx2.Response(200, json={"ok": True}))

    real_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(host: str, port: Any, *args: Any, **kwargs: Any) -> list[Any]:
        # The same `socket` module the database driver resolves its own host
        # with: only the names the test aims at are answered with a stub.
        if host.endswith((".example.com", ".example.net", ".example.org")):
            return [(2, 1, 6, "", (_PUBLIC, port))]
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr("app.core.sanitize.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        http_handler,
        "PinnedAsyncClient",
        lambda *, timeout: PinnedAsyncClient(timeout=timeout, transport=wire),
    )

    def install(responder: Callable[[httpx2.Request], httpx2.Response] | None = None) -> _Wire:
        if responder is not None:
            wire.responder = responder
        return wire

    return install


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _edge(source: NodeInstance, target: NodeInstance) -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port="out",
        target_node_id=target.id,
        target_port="in",
    )


def _graph(http_config: dict[str, Any], *, body: Any = None) -> tuple[WorkflowGraph, NodeInstance]:
    entry, call, output = (
        _node("core.input"),
        _node("http.request", http_config),
        _node("core.output"),
    )
    bindings = [
        Binding(
            target_node_id=output.id,
            target_field="structured",
            source=NodeOutputRef(node_id=call.id, port="out"),
        )
    ]
    if body is not None:
        bindings.append(
            Binding(target_node_id=call.id, target_field="body", source=LiteralValue(value=body))
        )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, call, output),
        edges=(_edge(entry, call), _edge(call, output)),
        bindings=tuple(bindings),
    )
    return graph, call


async def _secret(
    engine: AsyncEngine,
    member: tuple[User, Organization],
    value: HttpCredentialSecret | ApiKeySecret,
    *,
    visibility: Visibility = Visibility.ORG,
) -> uuid.UUID:
    user, org = member
    sealed = seal_secret(value, scope=VaultScope.organization(org.id))
    row = OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=f"secret-{uuid.uuid4().hex[:6]}",
        kind=value.kind.value,
        visibility=visibility.value,
        owner_user_id=user.id,
        sealed_secret=sealed.ciphertext,
        hint=sealed.hint,
        key_version=sealed.key_version,
    )
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        db.add(row)
        await db.commit()
    return row.id


async def _member(engine: AsyncEngine, *, role: str = "owner") -> tuple[User, Organization]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        member = await seed_member(db, role=role)
        await db.commit()
    return member


def _credential(*origins: str) -> HttpCredentialSecret:
    return HttpCredentialSecret(token=_TOKEN, origins=origins or ("https://api.example.com",))


async def _published(engine: AsyncEngine, seeded: SeededRun) -> None:
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, seeded.graph)


async def test_a_get_sends_the_credential_and_hands_back_a_redacted_response(
    engine: AsyncEngine, network
):
    member = await _member(engine)
    secret_id = await _secret(engine, member, _credential())
    wire = network(
        lambda _r: httpx2.Response(
            200,
            json={"echo": f"Bearer {_TOKEN}", "n": 1},
            headers={"Set-Cookie": "session=1", "X-Request-Id": "r-1"},
        )
    )
    graph, _call = _graph(
        {
            "url": "https://api.example.com/v1/items",
            "headers": {"X-Trace": "t-1"},
            "auth": {"kind": "bearer", "secret_id": str(secret_id)},
        }
    )
    seeded = await seed_run(engine, graph, member=member)
    await _published(engine, seeded)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    (sent,) = wire.sent
    assert sent.headers["Authorization"] == f"Bearer {_TOKEN}"
    assert sent.headers["X-Trace"] == "t-1"
    assert sent.url.host == _PUBLIC and sent.headers["Host"] == "api.example.com"
    assert run.output is not None
    response = run.output["structured"]
    assert response["status_code"] == 200
    assert response["body"] == {"echo": "Bearer [redacted]", "n": 1}
    assert "set-cookie" not in response["headers"]
    assert response["headers"]["x-request-id"] == "r-1"
    assert _TOKEN not in str(run.output)


@pytest.mark.security
async def test_a_basic_credential_echoed_back_is_redacted_in_its_encoded_form(
    engine: AsyncEngine, network
):
    """The Basic header carries base64 of `username:token`, which does not contain
    the token as stored - scrubbing only the raw token would hand it back whole."""
    member = await _member(engine)
    secret = HttpCredentialSecret(
        token=_TOKEN, username="svc", origins=("https://api.example.com",)
    )
    secret_id = await _secret(engine, member, secret)
    wire = network(
        lambda request: httpx2.Response(
            200,
            json={"echo": request.headers["Authorization"]},
            headers={"X-Echo": request.headers["Authorization"]},
        )
    )
    graph, _call = _graph(
        {
            "url": "https://api.example.com/v1/items",
            "auth": {"kind": "basic", "secret_id": str(secret_id)},
        }
    )
    seeded = await seed_run(engine, graph, member=member)
    await _published(engine, seeded)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    (sent,) = wire.sent
    encoded = base64.b64encode(f"svc:{_TOKEN}".encode()).decode()
    assert sent.headers["Authorization"] == f"Basic {encoded}"
    assert run.output is not None
    response = run.output["structured"]
    assert response["body"] == {"echo": "Basic [redacted]"}
    assert response["headers"]["x-echo"] == "Basic [redacted]"
    assert encoded not in str(run.output) and _TOKEN not in str(run.output)


@pytest.mark.security
async def test_a_url_outside_the_credentials_origins_is_refused_before_anything_is_sent(
    engine: AsyncEngine, network
):
    member = await _member(engine)
    secret_id = await _secret(engine, member, _credential("https://api.example.com"))
    wire = network()
    graph, _call = _graph(
        {
            "url": "https://attacker.example.net/collect",
            "auth": {"kind": "header", "secret_id": str(secret_id), "header_name": "X-Api-Key"},
        }
    )
    seeded = await seed_run(engine, graph, member=member)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "SECRET_ORIGIN_DENIED"
    assert wire.sent == []


@pytest.mark.security
@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1/admin", "http://169.254.169.254/latest/meta-data", "ftp://example.com/x"],
    ids=["loopback", "metadata", "not-http"],
)
async def test_an_address_inside_the_deployment_is_never_dialled(
    engine: AsyncEngine, network, url: str
):
    wire = network()
    graph, _call = _graph({"url": url})
    seeded = await seed_run(engine, graph)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "URL_REFUSED"
    assert wire.sent == []


@pytest.mark.security
async def test_a_redirect_to_another_origin_is_followed_without_the_credential(
    engine: AsyncEngine, network
):
    member = await _member(engine)
    secret_id = await _secret(engine, member, _credential())

    def responder(request: httpx2.Request) -> httpx2.Response:
        if request.headers["Host"] == "api.example.com":
            return httpx2.Response(302, headers={"Location": "https://cdn.example.org/file"})
        return httpx2.Response(200, text="done")

    wire = network(responder)
    graph, _call = _graph(
        {
            "url": "https://api.example.com/v1/file",
            "auth": {"kind": "bearer", "secret_id": str(secret_id)},
        }
    )
    seeded = await seed_run(engine, graph, member=member)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    first, second = wire.sent
    assert first.headers["Authorization"] == f"Bearer {_TOKEN}"
    assert "Authorization" not in second.headers
    assert second.headers["Host"] == "cdn.example.org"


async def test_a_response_over_the_limit_fails_rather_than_being_cut_short(
    engine: AsyncEngine, network
):
    network(lambda _r: httpx2.Response(200, content=b"x" * 5000))
    graph, _call = _graph({"url": "https://api.example.com/big", "max_response_bytes": 1000})
    seeded = await seed_run(engine, graph)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "RESPONSE_TOO_LARGE"


async def test_an_error_status_fails_the_step_unless_it_is_asked_for_as_output(
    engine: AsyncEngine, network
):
    network(lambda _r: httpx2.Response(404, json={"error": "missing"}))
    failing, _ = _graph({"url": "https://api.example.com/x"})
    completing, _ = _graph({"url": "https://api.example.com/x", "on_error_status": "complete"})

    failed = await drive(await seed_run(engine, failing))
    completed = await drive(await seed_run(engine, completing))

    assert failed.status == WorkflowRunStatus.FAILED.value
    assert failed.error is not None and failed.error["details"] == {"status_code": 404}
    assert completed.status == WorkflowRunStatus.SUCCEEDED.value
    assert completed.output is not None
    assert completed.output["structured"]["status_code"] == 404


def _times_out(_request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ReadTimeout("read timed out")


async def _attempt_guarantees(seeded: SeededRun) -> list[str | None]:
    async with seeded.factory() as db:
        rows = (
            await db.execute(
                select(NodeAttempt.retry_guarantee)
                .join(NodeRun, NodeRun.id == NodeAttempt.node_run_id)
                .where(NodeRun.workflow_run_id == seeded.run.id)
                .order_by(NodeAttempt.created_at)
            )
        ).scalars()
        return list(rows)


async def test_a_write_that_got_no_answer_stops_for_a_person_rather_than_retrying(
    engine: AsyncEngine, network
):
    """The far side may have acted, so sending it again could do it twice."""
    wire = network(_times_out)
    graph, _call = _graph(
        {"method": "POST", "url": "https://api.example.com/orders"}, body={"a": 1}
    )
    seeded = await seed_run(engine, graph)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.NEEDS_ATTENTION.value
    assert len(wire.sent) == 1
    assert "at_least_once" in await _attempt_guarantees(seeded)


async def test_a_write_with_an_idempotency_header_is_retried_with_the_same_key(
    engine: AsyncEngine, network
):
    wire = network(_times_out)
    graph, _call = _graph(
        {
            "method": "POST",
            "url": "https://api.example.com/orders",
            "idempotency_key_header": "Idempotency-Key",
        },
        body={"a": 1},
    )
    seeded = await seed_run(engine, graph)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.WAITING_RETRY.value
    (sent,) = wire.sent
    assert sent.headers["Idempotency-Key"].startswith(f"{seeded.org.id}:{seeded.run.id}:")
    assert sent.headers["Content-Type"] == "application/json"
    assert sent.content == b'{"a": 1}'
    assert "idempotent" in await _attempt_guarantees(seeded)


async def test_a_connection_that_never_opened_is_a_plain_retryable_failure(
    engine: AsyncEngine, network
):
    def refuses(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    network(refuses)
    graph, _call = _graph({"method": "DELETE", "url": "https://api.example.com/orders/1"})

    run = await drive(await seed_run(engine, graph))

    assert run.status == WorkflowRunStatus.WAITING_RETRY.value


@pytest.mark.security
async def test_a_secret_that_is_not_an_http_credential_cannot_be_published(
    engine: AsyncEngine, network
):
    member = await _member(engine)
    api_key = await _secret(engine, member, ApiKeySecret(api_key="sk-model-key-000"))
    graph, call = _graph(
        {"url": "https://api.example.com/x", "auth": {"kind": "bearer", "secret_id": str(api_key)}}
    )
    seeded = await seed_run(engine, graph, member=member)

    with pytest.raises(GraphValidationError) as refused:
        await _published(engine, seeded)

    fields = {problem["field"] for problem in refused.value.details["fields"]}
    assert f"nodes.{call.id}.config.auth.secret_id" in fields


@pytest.mark.security
async def test_a_credential_the_runs_principal_cannot_use_is_not_sent(engine: AsyncEngine, network):
    """A private secret someone else owns: a builder running the graph cannot reach it."""
    owner = await _member(engine, role="builder")
    _builder, org = owner
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        other = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password="x",
            is_active=True,
        )
        db.add(other)
        await db.commit()
    secret_id = await _secret(engine, (other, org), _credential(), visibility=Visibility.PRIVATE)
    wire = network()
    graph, _call = _graph(
        {
            "url": "https://api.example.com/x",
            "auth": {"kind": "bearer", "secret_id": str(secret_id)},
        }
    )
    seeded = await seed_run(engine, graph, member=owner)

    run = await drive(seeded)

    assert run.error is not None and run.error["code"] == "SECRET_NOT_USABLE"
    assert wire.sent == []


@pytest.mark.parametrize(
    ("config", "field"),
    [
        ({"url": "https://a.example", "headers": {"Authorization": "Bearer x"}}, "headers"),
        ({"url": "https://a.example", "auth": {"kind": "bearer"}}, "auth"),
        ({"url": "https://a.example", "auth": {"kind": "none", "header_name": "X-A"}}, "auth"),
        (
            {
                "url": "https://a.example",
                "auth": {"kind": "header", "secret_id": str(uuid.uuid4())},
            },
            "auth",
        ),
    ],
    ids=["authorization-header", "no-secret", "header-without-auth", "header-kind-without-name"],
)
async def test_a_config_that_could_smuggle_or_lose_a_credential_cannot_publish(
    engine: AsyncEngine, config: dict[str, Any], field: str
):
    graph, call = _graph(config)
    seeded = await seed_run(engine, graph)

    with pytest.raises(GraphValidationError) as refused:
        await _published(engine, seeded)

    assert any(
        problem["field"].startswith(f"nodes.{call.id}.config.{field}")
        or problem["field"] == f"nodes.{call.id}.config"
        for problem in refused.value.details["fields"]
    )


@pytest.mark.security
@pytest.mark.parametrize(
    ("auth", "header", "expected"),
    [
        ({"kind": "basic"}, "Authorization", "Basic YWRhOnRvay1hYmNkZWYtMTIzNDU2"),
        ({"kind": "header", "header_name": "X-Api-Key"}, "X-Api-Key", _TOKEN),
    ],
    ids=["basic", "header"],
)
async def test_the_credential_is_sent_the_way_the_step_says(
    engine: AsyncEngine, network, auth: dict[str, Any], header: str, expected: str
):
    member = await _member(engine)
    secret_id = await _secret(
        engine,
        member,
        HttpCredentialSecret(token=_TOKEN, username="ada", origins=("https://api.example.com",)),
    )
    wire = network()
    graph, _call = _graph(
        {"url": "https://api.example.com/x", "auth": {**auth, "secret_id": str(secret_id)}}
    )

    run = await drive(await seed_run(engine, graph, member=member))

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    (sent,) = wire.sent
    assert sent.headers[header] == expected


@pytest.mark.security
async def test_a_redirect_to_something_other_than_http_is_not_followed(
    engine: AsyncEngine, network
):
    wire = network(lambda _r: httpx2.Response(302, headers={"Location": "file:///etc/passwd"}))
    graph, _call = _graph({"url": "https://api.example.com/x"})

    run = await drive(await seed_run(engine, graph))

    assert run.error is not None and run.error["code"] == "URL_REFUSED"
    assert len(wire.sent) == 1


async def test_a_redirect_loop_stops(engine: AsyncEngine, network):
    wire = network(lambda _r: httpx2.Response(302, headers={"Location": "/again"}))
    graph, _call = _graph({"url": "https://api.example.com/x"})

    run = await drive(await seed_run(engine, graph))

    assert run.error is not None and run.error["code"] == "TOO_MANY_REDIRECTS"
    assert len(wire.sent) == http_handler.MAX_REDIRECTS + 1


async def test_a_body_that_claims_json_and_is_not_comes_back_as_text(engine: AsyncEngine, network):
    network(
        lambda _r: httpx2.Response(
            200, content=b"{not json", headers={"Content-Type": "application/json"}
        )
    )
    graph, _call = _graph({"url": "https://api.example.com/x"})

    run = await drive(await seed_run(engine, graph))

    assert run.output is not None and run.output["structured"]["body"] == "{not json"


@pytest.mark.security
async def test_a_query_credential_goes_in_its_parameter_and_is_redacted_from_the_echo(
    engine: AsyncEngine, network
):
    member = await _member(engine)
    secret_id = await _secret(engine, member, _credential())
    wire = network(lambda request: httpx2.Response(200, json={"called": str(request.url)}))
    graph, _call = _graph(
        {
            "url": "https://api.example.com/x?api_key=typed&q=1",
            "auth": {"kind": "query", "query_name": "api_key", "secret_id": str(secret_id)},
        }
    )

    run = await drive(await seed_run(engine, graph, member=member))

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    (sent,) = wire.sent
    assert sent.url.params["api_key"] == _TOKEN and sent.url.params["q"] == "1"
    assert "Authorization" not in sent.headers
    assert run.output is not None and _TOKEN not in str(run.output)


def _pages(pages: dict[str, dict[str, Any]]) -> Callable[[httpx2.Request], httpx2.Response]:
    """A server that answers each page by its query string, and 404s the rest."""

    def responder(request: httpx2.Request) -> httpx2.Response:
        key = request.url.query.decode()
        return httpx2.Response(200, json=pages[key]) if key in pages else httpx2.Response(404)

    return responder


async def _paged(engine: AsyncEngine, pagination: dict[str, Any], url: str) -> dict[str, Any]:
    graph, _call = _graph({"url": url, "pagination": pagination})
    run = await drive(await seed_run(engine, graph))
    assert run.status == WorkflowRunStatus.SUCCEEDED.value, run.error
    assert run.output is not None
    return run.output["structured"]


class TestPaging:
    async def test_a_next_url_is_followed_until_the_response_names_none(
        self, engine: AsyncEngine, network
    ):
        network(
            _pages(
                {
                    "": {"data": [1, 2], "links": {"next": "/items?after=2"}},
                    "after=2": {"data": [3], "links": {"next": None}},
                }
            )
        )
        result = await _paged(
            engine,
            {"mode": "next_url", "items_path": "data", "next_path": "links.next"},
            "https://api.example.com/items",
        )
        assert (result["items"], result["pages"], result["complete"]) == ([1, 2, 3], 2, True)
        assert result["body"] == {"data": [3], "links": {"next": None}}

    async def test_a_cursor_is_sent_back_in_its_parameter(self, engine: AsyncEngine, network):
        wire = network(
            _pages(
                {
                    "": {"results": ["a"], "meta": {"next": "c2"}},
                    "cursor=c2": {"results": ["b"], "meta": {"next": ""}},
                }
            )
        )
        result = await _paged(
            engine,
            {
                "mode": "cursor",
                "items_path": "results",
                "next_path": "meta.next",
                "param": "cursor",
            },
            "https://api.example.com/items",
        )
        assert result["items"] == ["a", "b"] and len(wire.sent) == 2

    async def test_pages_are_counted_until_one_is_empty(self, engine: AsyncEngine, network):
        network(
            _pages(
                {
                    "page=0": {"rows": [1]},
                    "page=1": {"rows": [2]},
                    "page=2": {"rows": []},
                }
            )
        )
        result = await _paged(
            engine,
            {"mode": "page", "items_path": "rows", "param": "page", "first_page": 0},
            "https://api.example.com/items",
        )
        assert (result["items"], result["pages"]) == ([1, 2], 3)

    async def test_paging_stops_at_its_maximum_and_says_there_was_more(
        self, engine: AsyncEngine, network
    ):
        wire = network(lambda request: httpx2.Response(200, json={"rows": [1]}))
        result = await _paged(
            engine,
            {"mode": "page", "items_path": "rows", "param": "page", "max_pages": 3},
            "https://api.example.com/items",
        )
        assert (result["items"], result["pages"], result["complete"]) == ([1, 1, 1], 3, False)
        assert len(wire.sent) == 3

    async def test_a_page_without_a_list_of_items_fails(self, engine: AsyncEngine, network):
        network(lambda _r: httpx2.Response(200, json={"rows": {"not": "a list"}}))
        graph, _call = _graph(
            {
                "url": "https://api.example.com/items",
                "pagination": {"mode": "page", "items_path": "rows", "param": "page"},
            }
        )
        run = await drive(await seed_run(engine, graph))
        assert run.error is not None and run.error["code"] == "PAGE_ITEMS_NOT_A_LIST"

    @pytest.mark.parametrize(
        "body", [{"rows": [1], "next": 7}, {"rows": [1], "next": "mailto:x@example.com"}]
    )
    async def test_a_next_page_that_is_not_an_http_url_ends_the_paging(
        self, engine: AsyncEngine, network, body
    ):
        wire = network(lambda _r: httpx2.Response(200, json=body))
        result = await _paged(
            engine,
            {"mode": "next_url", "items_path": "rows", "next_path": "next"},
            "https://api.example.com/items",
        )
        assert result["pages"] == 1 and len(wire.sent) == 1

    async def test_an_error_on_a_later_page_fails_the_step(self, engine: AsyncEngine, network):
        network(_pages({"": {"rows": [1], "next": "/items?after=1"}}))
        graph, _call = _graph(
            {
                "url": "https://api.example.com/items",
                "pagination": {"mode": "next_url", "items_path": "rows", "next_path": "next"},
            }
        )
        run = await drive(await seed_run(engine, graph))
        assert run.error is not None and run.error["code"] == "HTTP_ERROR_STATUS"

    async def test_every_page_together_stays_under_the_response_limit(
        self, engine: AsyncEngine, network
    ):
        network(lambda _r: httpx2.Response(200, json={"rows": ["x" * 400]}))
        graph, _call = _graph(
            {
                "url": "https://api.example.com/items",
                "max_response_bytes": 1000,
                "pagination": {"mode": "page", "items_path": "rows", "param": "page"},
            }
        )
        run = await drive(await seed_run(engine, graph))
        assert run.error is not None and run.error["code"] == "RESPONSE_TOO_LARGE"

    @pytest.mark.security
    async def test_a_next_page_on_another_origin_gets_no_credential(
        self, engine: AsyncEngine, network
    ):
        member = await _member(engine)
        secret_id = await _secret(engine, member, _credential())

        def responder(request: httpx2.Request) -> httpx2.Response:
            if request.headers["Host"] == "api.example.com":
                return httpx2.Response(
                    200, json={"rows": [1], "next": "https://cdn.example.org/p2"}
                )
            return httpx2.Response(200, json={"rows": [2]})

        wire = network(responder)
        graph, _call = _graph(
            {
                "url": "https://api.example.com/items",
                "auth": {"kind": "bearer", "secret_id": str(secret_id)},
                "pagination": {"mode": "next_url", "items_path": "rows", "next_path": "next"},
            }
        )
        run = await drive(await seed_run(engine, graph, member=member))

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        first, second = wire.sent
        assert first.headers["Authorization"] == f"Bearer {_TOKEN}"
        assert "Authorization" not in second.headers
