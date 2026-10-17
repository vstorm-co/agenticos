"""The terminal's `/knowledge` and `/sources` folders, as the runner resolves them.

The repositories, the vault and the connectors are stand-ins: what is under
test is which bases and sources an agent reaches, that a document reads back as
its text, and that a source's file is read with its own credential, within the
size limit, and closed when the run is over.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.capabilities.mirage import MIRAGE_TREES_RESOURCE, TreeUnavailable
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret
from app.services import mirage_mounts
from app.services.agent_runner import AgentRunnerService
from app.services.mirage_mounts import (
    MAX_FILE_BYTES,
    MirageMountService,
    _folder,
    _segments,
    _source_path,
    _unique,
    stitched,
)
from app.services.rag.connectors import CONNECTOR_REGISTRY, RemoteFile, RemoteListing
from app.services.rag.models import DocumentChunk

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()
OTHER_ORG = uuid.uuid4()
KEY = ApiKeySecret(api_key="sk-live-bucket-key")


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=ORG, role=OrgRoleName.OWNER)


def _kb(name: str, organization_id: uuid.UUID | None = ORG) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        organization_id=organization_id,
        collection_name=f"col_{name.lower().replace(' ', '_')}",
        vector_tenant=organization_id,
    )


def _source(name: str, connector_type: str, secret_id: uuid.UUID | None = None) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        connector_type=connector_type,
        config={"bucket": "reports"},
        secret_id=secret_id,
    )


class TestStitchingAParse:
    def test_the_splitters_overlap_is_kept_once(self) -> None:
        first = "The notice period is thirty days from the date of the written notice."
        second = "from the date of the written notice. Either party may end it early."
        assert stitched([first, second]) == (
            "The notice period is thirty days from the date of the written notice. "
            "Either party may end it early."
        )

    def test_chunks_with_nothing_in_common_are_a_paragraph_apart(self) -> None:
        assert stitched(["Page one ends here.", "Page two starts here."]) == (
            "Page one ends here.\n\nPage two starts here."
        )

    def test_a_short_chunk_is_never_taken_for_an_overlap(self) -> None:
        assert stitched(["Total: 12", "12"]) == "Total: 12\n\n12"

    def test_an_earlier_repeat_of_the_overlaps_start_is_passed_over(self) -> None:
        mark = "Clause 4.2 applies to"
        text = f"Intro. {mark} staff. {mark} contractors only."
        chunk = f"{mark} contractors only. New terms follow from here on, at length."
        assert stitched([text, chunk]) == (
            f"Intro. {mark} staff. {mark} contractors only. New terms follow from here on, at length."
        )

    def test_no_chunks_is_no_text(self) -> None:
        assert stitched([]) == ""


class TestNames:
    def test_a_folder_is_a_path_segment_and_never_taken_twice(self) -> None:
        taken: set[str] = set()
        assert _folder("Sales handbook", taken) == "Sales-handbook"
        assert _folder("sales  handbook", taken) == "sales-handbook-2"
        assert _folder("../..", taken) == "untitled"

    def test_a_second_file_of_the_same_name_is_numbered(self) -> None:
        taken: set[str] = set()
        assert [_unique("q3/report.pdf", taken) for _ in range(3)] == [
            "q3/report.pdf",
            "q3/report~2.pdf",
            "q3/report~3.pdf",
        ]

    def test_a_path_cannot_climb_out_of_its_folder(self) -> None:
        assert _segments("../../etc/./passwd") == "etc/passwd"
        assert _segments("a\\b") == "a/b"
        assert _segments("/") == "untitled"

    @pytest.mark.parametrize(
        ("connector_type", "remote", "expected"),
        [
            (
                "s3",
                {"id": "k", "name": "q3.pdf", "source_path": "s3://bucket/2026/q3.pdf"},
                "2026/q3.pdf",
            ),
            (
                "git",
                {"id": "docs/setup.md", "name": "setup.md", "source_path": "git://x"},
                "docs/setup.md",
            ),
            (
                "gdrive",
                {"id": "f1", "name": "Plan.docx", "source_path": "gdrive://f1"},
                "Plan.docx",
            ),
        ],
    )
    def test_a_source_keeps_its_own_folders_where_it_has_them(
        self, connector_type: str, remote: dict[str, str], expected: str
    ) -> None:
        source = _source("s", connector_type)
        assert _source_path(source, RemoteFile(**remote)) == expected


@pytest.fixture
def repos(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The three repositories the service reads, as mocks the test fills."""
    fakes = SimpleNamespace(
        bases=AsyncMock(return_value={}),
        documents=AsyncMock(return_value=[]),
        sources=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(mirage_mounts.knowledge_base_repo, "get_by_ids", fakes.bases)
    monkeypatch.setattr(mirage_mounts.rag_document_repo, "get_indexed_for_kb", fakes.documents)
    monkeypatch.setattr(mirage_mounts.sync_source_repo, "get_all", fakes.sources)
    return fakes


def _service(store: Any = None) -> MirageMountService:
    service = MirageMountService(MagicMock(), vector_store=lambda: store)
    service.secrets = MagicMock(resolve_for_bindings=AsyncMock(return_value={}))
    return service


def test_a_document_is_read_through_a_store_safe_on_any_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = object()
    monkeypatch.setattr(mirage_mounts, "unpooled_vector_store", lambda *_args: store)
    assert mirage_mounts._agent_vector_store() is store


class TestKnowledgeFolders:
    async def test_only_this_organizations_bound_bases_are_mounted(self, repos: Any) -> None:
        own, shared, foreign = _kb("Handbook"), _kb("Policies", None), _kb("Theirs", OTHER_ORG)
        gone = uuid.uuid4()
        repos.bases.return_value = {kb.id: kb for kb in (own, shared, foreign)}
        spec = AgentSpec(name="a", collection_ids=[own.id, gone, shared.id, foreign.id])

        trees = await _service().trees(_ctx(), spec, knowledge=True, sources=False)

        assert [tree.path for tree in trees] == ["/knowledge/Handbook/", "/knowledge/Policies/"]
        assert 'knowledge base "Handbook"' in trees[0].describe

    async def test_each_indexed_document_reads_back_as_its_text(self, repos: Any) -> None:
        kb = _kb("Handbook")
        repos.bases.return_value = {kb.id: kb}
        repos.documents.return_value = [
            SimpleNamespace(filename="hr/leave.md", vector_document_id="v1"),
            SimpleNamespace(filename="hr/leave.md", vector_document_id="v2"),
            SimpleNamespace(filename="draft.md", vector_document_id=None),
        ]
        store = MagicMock(
            get_document_chunks=AsyncMock(
                return_value=[
                    DocumentChunk(content="Holidays: 26 days"),
                    DocumentChunk(content="Ask HR."),
                ]
            )
        )
        [tree] = await _service(store).trees(
            _ctx(), AgentSpec(name="a", collection_ids=[kb.id]), knowledge=True, sources=False
        )

        files = await tree.list_files()
        text = await tree.read_file("hr/leave~2.md")

        assert [(file.path, file.size) for file in files] == [
            ("hr/leave.md", None),
            ("hr/leave~2.md", None),
        ]
        assert text == b"Holidays: 26 days\n\nAsk HR."
        store.get_document_chunks.assert_awaited_once_with(kb.collection_name, "v2", ORG)
        repos.sources.assert_not_awaited()

    async def test_neither_folder_kind_asked_for_is_nothing(self, repos: Any) -> None:
        kb = _kb("Handbook")
        repos.bases.return_value = {kb.id: kb}
        spec = AgentSpec(name="a", collection_ids=[kb.id])
        assert await _service().trees(_ctx(), spec, knowledge=False, sources=False) == ()


class FakeConnector:
    """A file store answering from memory, recording what it was handed."""

    listed: list[RemoteFile] = []
    seen: list[Any] = []
    closed: list[bool] = []
    close_fails = False

    async def list_files(self, config: dict[str, Any], credential: Any) -> RemoteListing:
        FakeConnector.seen.append(credential)
        return RemoteListing(files=FakeConnector.listed)

    async def download_file(
        self, file: RemoteFile, dest_dir: Path, config: Any = None, credential: Any = None
    ) -> Path:
        path = dest_dir / file.name
        path.write_bytes(b"revenue up")
        return path

    async def aclose(self) -> None:
        FakeConnector.closed.append(True)
        if FakeConnector.close_fails:
            raise RuntimeError("clone already gone")


@pytest.fixture
def connector(monkeypatch: pytest.MonkeyPatch) -> type[FakeConnector]:
    FakeConnector.listed = [
        RemoteFile(id="1", name="q3.txt", size=10, source_path="s3://reports/2026/q3.txt"),
        RemoteFile(
            id="2", name="big.bin", size=MAX_FILE_BYTES + 1, source_path="s3://reports/big.bin"
        ),
        # No size declared: only the download can say how large it is.
        RemoteFile(id="3", name="huge.bin", size=None, source_path="s3://reports/huge.bin"),
    ]
    FakeConnector.seen, FakeConnector.closed, FakeConnector.close_fails = [], [], False
    monkeypatch.setitem(CONNECTOR_REGISTRY, "s3", FakeConnector)
    return FakeConnector


class TestSourceFolders:
    async def test_this_organizations_file_stores_are_mounted_with_their_own_key(
        self, repos: Any, connector: type[FakeConnector]
    ) -> None:
        kb = _kb("Finance")
        secret_id = uuid.uuid4()
        repos.bases.return_value = {kb.id: kb}
        repos.sources.return_value = [
            _source("Reports bucket", "s3", secret_id),
            _source("Company site", "web"),
        ]
        service = _service()
        service.secrets.resolve_for_bindings.return_value = {secret_id: KEY}
        ctx = _ctx()

        [tree] = await service.trees(
            ctx, AgentSpec(name="a", collection_ids=[kb.id]), knowledge=False, sources=True
        )
        files = await tree.list_files()

        assert tree.path == "/sources/Reports-bucket/"
        assert [file.path for file in files] == ["2026/q3.txt", "big.bin", "huge.bin"]
        assert await tree.read_file("2026/q3.txt") == b"revenue up"
        assert connector.seen == [KEY]
        repos.sources.assert_awaited_once_with(
            service.db, organization_id=ORG, collection_name=kb.collection_name, is_active=True
        )
        service.secrets.resolve_for_bindings.assert_awaited_once_with(ctx, [secret_id])

    async def test_a_file_past_the_limit_is_refused_by_size_declared_or_found(
        self, repos: Any, connector: type[FakeConnector], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kb = _kb("Finance")
        repos.bases.return_value = {kb.id: kb}
        repos.sources.return_value = [_source("Bucket", "s3")]
        [tree] = await _service().trees(
            _ctx(), AgentSpec(name="a", collection_ids=[kb.id]), knowledge=False, sources=True
        )
        await tree.list_files()

        with pytest.raises(TreeUnavailable, match="larger than 20 MB"):
            await tree.read_file("big.bin")
        # `huge.bin` declared no size, so only what landed on disk can refuse it.
        monkeypatch.setattr(mirage_mounts, "MAX_FILE_BYTES", 5)
        with pytest.raises(TreeUnavailable, match="larger than"):
            await tree.read_file("huge.bin")
        assert connector.seen == [None]

    async def test_closing_releases_the_connector_and_survives_its_failure(
        self, repos: Any, connector: type[FakeConnector]
    ) -> None:
        kb = _kb("Finance")
        repos.bases.return_value = {kb.id: kb}
        repos.sources.return_value = [_source("Bucket", "s3")]
        [tree] = await _service().trees(
            _ctx(), AgentSpec(name="a", collection_ids=[kb.id]), knowledge=False, sources=True
        )

        await tree.close()
        connector.close_fails = True
        await tree.close()

        assert connector.closed == [True, True]


class TestTheRunnerResolvesThem:
    def _spec(self, **binding: Any) -> AgentSpec:
        return AgentSpec(
            name="a",
            capabilities=[CapabilityBindingSpec(id="mirage", **binding)],
        )

    async def test_a_terminal_mounting_platform_folders_gets_them(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trees = AsyncMock(return_value=("tree",))
        monkeypatch.setattr(MirageMountService, "trees", trees)
        resources: dict[str, Any] = {}

        await AgentRunnerService(MagicMock())._add_mirage_trees(
            resources, _ctx(), self._spec(config={"sources": True})
        )

        assert resources[MIRAGE_TREES_RESOURCE] == ("tree",)
        assert trees.await_args.kwargs == {"knowledge": True, "sources": True}

    @pytest.mark.parametrize(
        "spec",
        [
            AgentSpec(name="a"),
            AgentSpec(
                name="a",
                capabilities=[CapabilityBindingSpec(id="mirage", enabled=False)],
            ),
            AgentSpec(
                name="a",
                capabilities=[
                    CapabilityBindingSpec(
                        id="mirage",
                        config={"knowledge": False, "github": True, "repositories": ["a/b"]},
                    )
                ],
            ),
        ],
    )
    async def test_no_terminal_or_only_github_resolves_nothing(
        self, spec: AgentSpec, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trees = AsyncMock()
        monkeypatch.setattr(MirageMountService, "trees", trees)
        resources: dict[str, Any] = {}

        await AgentRunnerService(MagicMock())._add_mirage_trees(resources, _ctx(), spec)

        assert resources == {}
        trees.assert_not_awaited()
