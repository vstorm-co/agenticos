"""`http.download`, `http.upload` and a run's file route, end to end (#1791).

The network is replaced by a recording transport behind the real
`PinnedAsyncClient`, so the SSRF check, the redirect walk and the credential
rules all run as they would in production; storage is a temporary directory.
"""

from __future__ import annotations

import socket
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx2
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api import deps
from app.core.config import settings
from app.core.pinned_http import PinnedAsyncClient
from app.core.secret_kinds import HttpCredentialSecret, seal_secret
from app.core.vault import VaultScope
from app.db.models.organization import Organization
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_file import WorkflowFile
from app.db.models.workflow_run import ResourceRef, WorkflowRun, WorkflowRunMode, WorkflowRunStatus
from app.main import app
from app.services.file_storage import LocalFileStorage
from app.services.workflow_execution import WorkflowExecutionService
from app.workflows.contracts.io import Binding, FileRef, NodeOutputRef
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.nodes.http_download import _handler as download_handler
from app.workflows.nodes.http_upload import _handler as upload_handler
from tests.integration.workflow_run_support import SeededRun, drive, seed_member, seed_run

pytestmark = pytest.mark.anyio

_PUBLIC = "93.184.216.34"
_TOKEN = "tok-abcdef-123456"
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class _Wire(httpx2.AsyncBaseTransport):
    def __init__(self, responder: Callable[[httpx2.Request], httpx2.Response]) -> None:
        self.responder = responder
        self.sent: list[httpx2.Request] = []
        self.bodies: list[bytes] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.bodies.append(await request.aread())
        self.sent.append(request)
        return self.responder(request)


@pytest.fixture(autouse=True)
def storage(tmp_path: Path) -> Iterator[LocalFileStorage]:
    local = LocalFileStorage(tmp_path)
    with (
        patch("app.workflows.files.get_file_storage", return_value=local),
        patch("app.services.file_storage.get_file_storage", return_value=local),
        patch("app.api.routes.v1._stored_bytes.get_file_storage", return_value=local),
    ):
        yield local


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> Callable[..., _Wire]:
    wire = _Wire(lambda _r: httpx2.Response(200, content=_PNG))
    real_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(host: str, port: Any, *args: Any, **kwargs: Any) -> list[Any]:
        if host.endswith((".example.com", ".example.net")):
            return [(2, 1, 6, "", (_PUBLIC, port))]
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr("app.core.sanitize.socket.getaddrinfo", fake_getaddrinfo)
    for module in (download_handler, upload_handler):
        monkeypatch.setattr(
            module,
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


def _chain(step: NodeInstance, *, bindings: tuple[Binding, ...] = ()) -> WorkflowGraph:
    entry, output = _node("core.input"), _node("core.output")
    return WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, step, output),
        edges=(
            Edge(
                id=uuid.uuid4(),
                source_node_id=entry.id,
                source_port="out",
                target_node_id=step.id,
                target_port="in",
            ),
            Edge(
                id=uuid.uuid4(),
                source_node_id=step.id,
                source_port="out",
                target_node_id=output.id,
                target_port="in",
            ),
        ),
        bindings=(
            *bindings,
            Binding(
                target_node_id=output.id,
                target_field="structured",
                source=NodeOutputRef(node_id=step.id, port="out"),
            ),
        ),
    )


async def _error(seeded: SeededRun) -> dict[str, Any]:
    run = await drive(seeded)
    assert run.status == WorkflowRunStatus.FAILED.value, run.status
    assert run.error is not None
    return run.error


async def _member(engine: AsyncEngine) -> tuple[User, Organization]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        member = await seed_member(db)
        await db.commit()
    return member


async def _secret(engine: AsyncEngine, member: tuple[User, Organization], *origins: str) -> str:
    user, org = member
    value = HttpCredentialSecret(token=_TOKEN, origins=origins or ("https://files.example.com",))
    sealed = seal_secret(value, scope=VaultScope.organization(org.id))
    row = OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=f"s-{uuid.uuid4().hex[:6]}",
        kind=value.kind.value,
        visibility=Visibility.ORG.value,
        owner_user_id=user.id,
        sealed_secret=sealed.ciphertext,
        hint=sealed.hint,
        key_version=sealed.key_version,
    )
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        db.add(row)
        await db.commit()
    return str(row.id)


class TestDownloading:
    async def test_a_file_is_stored_with_the_type_its_bytes_show(self, engine, storage, network):
        wire = network(
            lambda _r: httpx2.Response(200, content=_PNG, headers={"Content-Type": "text/html"})
        )
        step = _node("http.download", {"url": "https://files.example.com/a/chart.png"})
        seeded = await seed_run(engine, _chain(step))
        run = await drive(seeded)

        answer = run.output["structured"]
        assert answer["content_type"] == "image/png"
        assert answer["filename"] == "chart.png" and answer["status_code"] == 200
        async with seeded.factory() as db:
            row = await db.get(WorkflowFile, uuid.UUID(answer["file"]["file_id"]))
        assert row is not None and row.workflow_run_id == seeded.run.id
        assert row.producing_node_run_id is not None
        assert await storage.load(row.storage_path) == _PNG
        assert wire.sent[0].method == "GET"

    async def test_a_redirect_is_followed_and_the_credential_stays_behind(self, engine, network):
        member = await _member(engine)
        secret_id = await _secret(engine, member)

        def answer(request: httpx2.Request) -> httpx2.Response:
            if request.url.path == "/start":
                return httpx2.Response(302, headers={"Location": "https://cdn.example.net/f"})
            return httpx2.Response(200, content=b"%PDF-1.7 body")

        wire = network(answer)
        step = _node(
            "http.download",
            {
                "url": "https://files.example.com/start",
                "auth": {"kind": "bearer", "secret_id": secret_id},
                "expected_content_types": ["application/pdf"],
                "filename": "report.pdf",
            },
        )
        run = await drive(await seed_run(engine, _chain(step), member=member))
        assert run.output["structured"]["filename"] == "report.pdf"
        first, second = wire.sent
        assert first.headers["Authorization"] == f"Bearer {_TOKEN}"
        assert "Authorization" not in second.headers

    async def test_a_query_credential_goes_only_where_it_may(self, engine, network):
        member = await _member(engine)
        secret_id = await _secret(engine, member)

        def answer(request: httpx2.Request) -> httpx2.Response:
            if request.url.path == "/start":
                return httpx2.Response(302, headers={"Location": "https://cdn.example.net/f"})
            return httpx2.Response(200, content=b"%PDF-1.7 body")

        wire = network(answer)
        auth = {"kind": "query", "query_name": "key", "secret_id": secret_id}
        step = _node(
            "http.download",
            {"url": "https://files.example.com/start", "auth": auth, "filename": "r.pdf"},
        )
        await drive(await seed_run(engine, _chain(step), member=member))
        first, second = wire.sent
        assert first.url.params["key"] == _TOKEN
        assert "key" not in second.url.params

    @pytest.mark.parametrize(
        ("responder", "config", "code"),
        [
            (
                lambda _r: httpx2.Response(200, content=b"<html>"),
                {"expected_content_types": ["image/png"]},
                "CONTENT_TYPE_MISMATCH",
            ),
            (
                lambda _r: httpx2.Response(200, content=b"x" * 64),
                {"max_bytes": 10},
                "RESPONSE_TOO_LARGE",
            ),
            (lambda _r: httpx2.Response(404), {}, "HTTP_ERROR_STATUS"),
            (lambda _r: httpx2.Response(302, headers={"Location": "ftp://x"}), {}, "URL_REFUSED"),
            (
                lambda _r: httpx2.Response(302, headers={"Location": "/again"}),
                {},
                "TOO_MANY_REDIRECTS",
            ),
        ],
        ids=["wrong-type", "too-large", "not-found", "bad-redirect", "redirect-loop"],
    )
    async def test_what_it_will_not_store(self, engine, storage, network, responder, config, code):
        network(responder)
        step = _node("http.download", {"url": "https://files.example.com/x", **config})
        seeded = await seed_run(engine, _chain(step))
        assert (await _error(seeded))["code"] == code
        assert not any(path.is_file() for path in Path(storage.base_dir).rglob("*"))

    @pytest.mark.security
    async def test_an_address_inside_the_deployment_is_refused_before_dialling(
        self, engine, network
    ):
        wire = network()
        for url, code in [
            ("http://127.0.0.1/x", "URL_REFUSED"),
            ("file:///etc/passwd", "URL_REFUSED"),
        ]:
            seeded = await seed_run(engine, _chain(_node("http.download", {"url": url})))
            assert (await _error(seeded))["code"] == code
        assert wire.sent == []

    async def test_a_server_that_cannot_be_reached_or_answers_nothing_is_retried(
        self, engine, network
    ):
        for error, code in [
            (httpx2.ConnectError("down"), "HTTP_UNREACHABLE"),
            (httpx2.ReadTimeout("slow"), "HTTP_NO_RESPONSE"),
        ]:

            def refuse(_request: httpx2.Request, error: Exception = error) -> httpx2.Response:
                raise error

            network(refuse)
            seeded = await seed_run(
                engine, _chain(_node("http.download", {"url": "https://files.example.com/x"}))
            )
            run = await drive(seeded)
            assert run.status == WorkflowRunStatus.WAITING_RETRY.value, code

    async def test_a_credential_that_is_gone_sends_nothing(self, engine, network):
        wire = network()
        step = _node(
            "http.download",
            {
                "url": "https://files.example.com/x",
                "auth": {"kind": "bearer", "secret_id": str(uuid.uuid4())},
            },
        )
        seeded = await seed_run(engine, _chain(step))
        assert (await _error(seeded))["code"] == "SECRET_NOT_USABLE"
        assert wire.sent == []


class TestUploading:
    async def test_a_file_is_streamed_with_its_type_and_the_stable_key(
        self, engine, storage, network
    ):
        wire = network(lambda _r: httpx2.Response(201, json={"id": "remote-1"}))
        member = await _member(engine)
        earlier = await seed_run(engine, _chain(_node("debug.echo")), member=member)
        ref = await _stored(engine, storage, earlier.run, b"%PDF-1.7 hi", "application/pdf")
        step = _node(
            "http.upload",
            {
                "url": "https://files.example.com/in",
                "method": "PUT",
                "idempotency_key_header": "Idempotency-Key",
            },
        )
        seeded = await seed_run(
            engine,
            _chain(
                step, bindings=(Binding(target_node_id=step.id, target_field="file", source=ref),)
            ),
            member=member,
        )
        await _import(seeded, ref)

        run = await drive(seeded)

        assert run.output["structured"]["body"] == {"id": "remote-1"}
        (sent,) = wire.sent
        assert sent.method == "PUT" and wire.bodies == [b"%PDF-1.7 hi"]
        assert sent.headers["Content-Type"] == "application/pdf"
        assert sent.headers["Idempotency-Key"]

    async def test_a_lost_answer_is_uncertain_without_a_key_and_retried_with_one(
        self, engine, storage, network
    ):
        def silent(_request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ReadTimeout("slow")

        network(silent)
        for extra, status in [
            ({}, WorkflowRunStatus.NEEDS_ATTENTION.value),
            ({"idempotency_key_header": "Idempotency-Key"}, WorkflowRunStatus.WAITING_RETRY.value),
        ]:
            seeded = await _upload_run(engine, storage, extra)
            run = await drive(seeded)
            assert run.status == status

    async def test_what_it_will_not_send_or_accept(self, engine, storage, network):
        for responder, extra, code in [
            (lambda _r: httpx2.Response(500), {}, "HTTP_ERROR_STATUS"),
            (
                lambda _r: httpx2.Response(200, content=b"x" * 64),
                {"max_response_bytes": 4},
                "RESPONSE_TOO_LARGE",
            ),
            (lambda _r: httpx2.Response(200), {"url": "http://127.0.0.1/in"}, "URL_REFUSED"),
            (lambda _r: httpx2.Response(200), {"url": "ftp://x"}, "URL_REFUSED"),
        ]:
            network(responder)
            seeded = await _upload_run(engine, storage, extra)
            assert (await _error(seeded))["code"] == code

    async def test_an_unreachable_server_is_retried(self, engine, storage, network):
        def down(_request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("down")

        network(down)
        run = await drive(await _upload_run(engine, storage, {}))
        assert run.status == WorkflowRunStatus.WAITING_RETRY.value

    @pytest.mark.security
    async def test_a_file_the_run_was_not_given_is_not_sent(self, engine, storage, network):
        wire = network()
        seeded = await _upload_run(engine, storage, {}, imported=False)
        assert (await _error(seeded))["code"] == "FILE_NOT_FOUND"
        assert wire.sent == []

    async def test_a_credential_that_is_gone_or_misaimed_sends_nothing(
        self, engine, storage, network
    ):
        wire = network()
        member = await _member(engine)
        secret_id = await _secret(engine, member, "https://other.example.com")
        for secret, code in [
            (str(uuid.uuid4()), "SECRET_NOT_USABLE"),
            (secret_id, "SECRET_ORIGIN_DENIED"),
        ]:
            seeded = await _upload_run(
                engine, storage, {"auth": {"kind": "bearer", "secret_id": secret}}, member=member
            )
            assert (await _error(seeded))["code"] == code
        assert wire.sent == []

    async def test_a_credential_it_may_send_goes_with_the_file(self, engine, storage, network):
        wire = network(lambda _r: httpx2.Response(200, json={}))
        member = await _member(engine)
        secret_id = await _secret(engine, member)
        seeded = await _upload_run(
            engine,
            storage,
            {"auth": {"kind": "bearer", "secret_id": secret_id}, "headers": {"X-Trace": "t"}},
            member=member,
        )
        await drive(seeded)
        (sent,) = wire.sent
        assert sent.headers["Authorization"] == f"Bearer {_TOKEN}"
        assert sent.headers["X-Trace"] == "t"

    async def test_a_query_credential_goes_in_the_upload_url(self, engine, storage, network):
        wire = network(lambda _r: httpx2.Response(200, json={}))
        member = await _member(engine)
        secret_id = await _secret(engine, member)
        auth = {"kind": "query", "query_name": "key", "secret_id": secret_id}
        await drive(await _upload_run(engine, storage, {"auth": auth}, member=member))
        (sent,) = wire.sent
        assert sent.url.params["key"] == _TOKEN

    async def test_a_file_whose_bytes_are_gone_is_not_sent(self, engine, storage, network):
        wire = network()
        seeded = await _upload_run(engine, storage, {})

        async def gone(_path: str) -> Any:
            raise FileNotFoundError

        with patch.object(storage, "open_stream", new=gone):
            assert (await _error(seeded))["code"] == "FILE_NOT_FOUND"
        assert wire.sent == []

    async def test_the_graph_s_author_is_checked_for_the_credential(self, engine):
        member = await _member(engine)
        ctx = SeededRun(
            run=MagicMock(),
            graph=MagicMock(),
            principal=member[0],
            org=member[1],
            factory=MagicMock(),
        ).ctx
        missing = {"kind": "bearer", "secret_id": str(uuid.uuid4())}
        async with async_sessionmaker(engine)() as db:
            for module, config in [
                (
                    download_handler,
                    download_handler.HttpDownloadConfig(
                        url="https://files.example.com/x", headers={"X-A": "1"}, auth=missing
                    ),
                ),
                (
                    upload_handler,
                    upload_handler.HttpUploadConfig(
                        url="https://files.example.com/x", headers={"X-A": "1"}, auth=missing
                    ),
                ),
            ]:
                assert [field for field, _ in await module.check_resources(db, ctx, config)] == [
                    "auth.secret_id"
                ]

    async def test_a_step_given_nothing_says_so(self):
        for module in (download_handler, upload_handler):
            result = await module.handle(None, None)
            assert result.error.code == "REQUEST_NOT_CONFIGURED"
        assert await download_handler.check_resources(MagicMock(), MagicMock(), MagicMock()) == []
        assert await upload_handler.check_resources(MagicMock(), MagicMock(), MagicMock()) == []


async def _stored(
    engine: AsyncEngine, storage: LocalFileStorage, run: WorkflowRun, data: bytes, content_type: str
) -> FileRef:
    file_id = uuid.uuid4()
    path = f"workflow-files/{run.organization_id}/{run.id}/{file_id}"
    await storage.save_at(path, data)
    async with async_sessionmaker(engine)() as db:
        db.add(
            WorkflowFile(
                id=file_id,
                organization_id=run.organization_id,
                workflow_run_id=run.id,
                storage_path=path,
                content_type=content_type,
                byte_size=len(data),
                filename="doc.pdf",
            )
        )
        await db.commit()
    return FileRef(file_id=file_id, content_type=content_type, byte_size=len(data))


async def _import(seeded: SeededRun, ref: FileRef) -> None:
    async with seeded.factory() as db:
        db.add(
            ResourceRef(
                organization_id=seeded.org.id,
                workflow_run_id=seeded.run.id,
                kind="file",
                ref=ref.model_dump(mode="json"),
            )
        )
        await db.commit()


async def _upload_run(
    engine: AsyncEngine,
    storage: LocalFileStorage,
    extra: dict[str, Any],
    *,
    imported: bool = True,
    member: tuple[User, Organization] | None = None,
) -> SeededRun:
    member = member or await _member(engine)
    earlier = await seed_run(engine, _chain(_node("debug.echo")), member=member)
    ref = await _stored(engine, storage, earlier.run, b"%PDF-1.7", "application/pdf")
    step = _node("http.upload", {"url": "https://files.example.com/in", **extra})
    seeded = await seed_run(
        engine,
        _chain(step, bindings=(Binding(target_node_id=step.id, target_field="file", source=ref),)),
        member=member,
    )
    if imported:
        await _import(seeded, ref)
    return seeded


class TestAFileBoundInAGraph:
    async def test_admission_imports_it_and_its_step_reads_it(self, engine, storage):
        member = await _member(engine)
        user, org = member
        earlier = await seed_run(engine, _chain(_node("debug.echo")), member=member)
        ref = await _stored(engine, storage, earlier.run, b"imported words", "text/plain")
        read = _node("file.read")
        graph = _chain(
            read, bindings=(Binding(target_node_id=read.id, target_field="file", source=ref),)
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            workflow = Workflow(
                id=uuid.uuid4(),
                organization_id=org.id,
                owner_user_id=user.id,
                slug=f"wf-{uuid.uuid4().hex[:8]}",
                name="Reads a file",
                status=WorkflowStatus.PUBLISHED.value,
                visibility=Visibility.PRIVATE.value,
                draft_graph=graph.model_dump(mode="json"),
            )
            db.add(workflow)
            await db.commit()
        ctx = SeededRun(run=earlier.run, graph=graph, principal=user, org=org, factory=factory).ctx
        with patch("app.worker.tasks.workflow_tasks.run_deployment"):
            async with factory() as db:
                started = await WorkflowExecutionService(db).start(
                    ctx, workflow.id, mode=WorkflowRunMode.TEST
                )
                await db.commit()
        async with factory() as db:
            run = await db.get(WorkflowRun, started.id)
            refs = (
                (
                    await db.execute(
                        select(ResourceRef).where(ResourceRef.workflow_run_id == started.id)
                    )
                )
                .scalars()
                .all()
            )
        assert run is not None and [r.ref["file_id"] for r in refs] == [str(ref.file_id)]
        finished = await drive(
            SeededRun(run=run, graph=graph, principal=user, org=org, factory=factory)
        )
        assert finished.output["structured"]["text"] == "imported words"


@pytest.fixture
async def http(engine: AsyncEngine, mock_redis: MagicMock):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    member = await _member(engine)

    async def session():
        async with factory() as opened:
            try:
                yield opened
                await opened.commit()
            except BaseException:
                await opened.rollback()
                raise

    seeded_ctx: list[Any] = []
    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_auth_context] = lambda: seeded_ctx[0]
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, member, seeded_ctx
    app.dependency_overrides.clear()


class TestServingARunsFile:
    async def test_a_run_s_file_downloads_and_another_run_s_does_not(self, engine, storage, http):
        client, member, seeded_ctx = http
        mine = await seed_run(engine, _chain(_node("debug.echo")), member=member)
        other = await seed_run(engine, _chain(_node("debug.echo")), member=member)
        seeded_ctx.append(mine.ctx)
        ref = await _stored(engine, storage, mine.run, b"%PDF-1.7 mine", "application/pdf")
        theirs = await _stored(engine, storage, other.run, b"%PDF-1.7 theirs", "application/pdf")
        base = f"{settings.API_V1_STR}/workflow-runs/{mine.run.id}/files"

        listed = await client.get(base)
        assert [item["id"] for item in listed.json()["items"]] == [str(ref.file_id)]

        served = await client.get(f"{base}/{ref.file_id}")
        assert served.status_code == 200 and served.content == b"%PDF-1.7 mine"
        assert served.headers["content-disposition"].startswith("attachment")
        assert served.headers["x-content-type-options"] == "nosniff"

        assert (await client.get(f"{base}/{theirs.file_id}")).status_code == 404

        async with mine.factory() as db:
            row = await db.get(WorkflowFile, ref.file_id)
            assert row is not None
            await storage.delete(row.storage_path)
        assert (await client.get(f"{base}/{ref.file_id}")).status_code == 404

    async def test_a_file_with_no_name_downloads_under_its_id(self, engine, storage, http):
        client, member, seeded_ctx = http
        mine = await seed_run(engine, _chain(_node("debug.echo")), member=member)
        seeded_ctx.append(mine.ctx)
        ref = await _stored(engine, storage, mine.run, b"words", "text/plain")
        async with mine.factory() as db:
            row = await db.get(WorkflowFile, ref.file_id)
            assert row is not None
            row.filename = None
            await db.commit()
        served = await client.get(
            f"{settings.API_V1_STR}/workflow-runs/{mine.run.id}/files/{ref.file_id}"
        )
        assert str(ref.file_id) in served.headers["content-disposition"]
