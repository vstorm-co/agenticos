"""The file steps against a real Postgres and a real storage directory (#1791).

Each test drives a graph through the dispatcher the way a worker does, so what
is proved is the whole path: a step reads a file only through its run's own
lookup, stores what it makes as a file of the run, and fails with a typed code
- never a parser's exception - on a file it cannot read.
"""

from __future__ import annotations

import io
import itertools
import json
import uuid
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pymupdf
import pytest
from docx import Document
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import settings
from app.core.permissions import AuthContext
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.models.workflow_file import WorkflowFile
from app.db.models.workflow_run import ResourceRef, WorkflowRun, WorkflowRunStatus
from app.services.file_storage import LocalFileStorage
from app.workflows import files
from app.workflows.contracts.io import Binding, FileRef, LiteralValue, NodeOutputRef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from tests.integration.workflow_run_support import SeededRun, drive, seed_member, seed_run

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def storage(tmp_path: Path) -> Iterator[LocalFileStorage]:
    local = LocalFileStorage(tmp_path)
    with (
        patch("app.workflows.files.get_file_storage", return_value=local),
        patch("app.services.file_storage.get_file_storage", return_value=local),
    ):
        yield local


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


def _chain(*steps: NodeInstance, bindings: list[Binding]) -> WorkflowGraph:
    """`core.input` -> the steps in order -> `core.output`, the last step's output
    as the run's `structured` answer."""
    entry, output = _node("core.input"), _node("core.output")
    nodes = (entry, *steps, output)
    edges = tuple(_edge(a, b) for a, b in itertools.pairwise(nodes))
    answer = Binding(
        target_node_id=output.id,
        target_field="structured",
        source=NodeOutputRef(node_id=steps[-1].id, port="out"),
    )
    return WorkflowGraph(
        entry_node_id=entry.id, nodes=nodes, edges=edges, bindings=(*bindings, answer)
    )


def _literal(node: NodeInstance, field: str, value: Any) -> Binding:
    return Binding(target_node_id=node.id, target_field=field, source=LiteralValue(value=value))


def _from(node: NodeInstance, source: NodeInstance, *path: str) -> Binding:
    return Binding(
        target_node_id=node.id,
        target_field=path[-1] if path else "file",
        source=NodeOutputRef(node_id=source.id, port="out", field_path=path),
    )


async def _member(engine: AsyncEngine) -> tuple[User, Organization]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        member = await seed_member(db)
        await db.commit()
    return member


async def _stored(
    engine: AsyncEngine,
    storage: LocalFileStorage,
    run: WorkflowRun,
    data: bytes,
    *,
    content_type: str,
    filename: str | None = None,
) -> FileRef:
    """A file the given run made, stored the way `files.save` stores one."""
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
                filename=filename,
            )
        )
        await db.commit()
    return FileRef(file_id=file_id, content_type=content_type, byte_size=len(data))


async def _import(seeded: SeededRun, ref: FileRef) -> None:
    """Record `ref` as a file the run was started with, as admission does."""
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


async def _run_on(
    engine: AsyncEngine,
    storage: LocalFileStorage,
    graph_for: Any,
    data: bytes,
    *,
    content_type: str,
    filename: str | None = None,
) -> tuple[WorkflowRun, SeededRun]:
    """Drive `graph_for(ref)` on a file an earlier run made and this one was started with."""
    member = await _member(engine)
    earlier = await seed_run(engine, _chain(_node("debug.echo"), bindings=[]), member=member)
    ref = await _stored(
        engine, storage, earlier.run, data, content_type=content_type, filename=filename
    )
    seeded = await seed_run(engine, graph_for(ref), member=member)
    await _import(seeded, ref)
    return await drive(seeded), seeded


async def _error(seeded: SeededRun) -> dict[str, Any]:
    async with seeded.factory() as db:
        run = (
            await db.execute(select(WorkflowRun).where(WorkflowRun.id == seeded.run.id))
        ).scalar_one()
    assert run.status == WorkflowRunStatus.FAILED.value, run.status
    assert run.error is not None
    return run.error


async def _saved(seeded: SeededRun, ref: dict[str, Any]) -> bytes:
    async with seeded.factory() as db:
        row = await db.get(WorkflowFile, uuid.UUID(ref["file_id"]))
    assert row is not None and row.workflow_run_id == seeded.run.id
    return await files.get_file_storage().load(row.storage_path)


def _one_step(definition_id: str, config: dict[str, Any] | None = None):
    def graph_for(ref: FileRef) -> WorkflowGraph:
        step = _node(definition_id, config)
        return _chain(step, bindings=[_literal(step, "file", ref.model_dump(mode="json"))])

    return graph_for


class TestWritingAndReading:
    async def test_text_json_and_rows_are_written_and_read_back_exactly(self, engine):
        for fmt, field, value, read_as in [
            ("text", "text", "Zażółć gęślą jaźń", "text"),
            ("json", "json_value", {"leads": [1, 2]}, "json"),
            ("csv", "rows", [{"name": "Ada", "score": 9}, {"name": "Linus", "extra": True}], "csv"),
        ]:
            write = _node("file.write", {"format": fmt, "filename": f"out.{fmt}"})
            read = _node("file.read", {"parse_as": read_as})
            graph = _chain(
                write,
                read,
                bindings=[_literal(write, field, value), _from(read, write, "file")],
            )
            run = await drive(await seed_run(engine, graph))
            assert run.status == WorkflowRunStatus.SUCCEEDED.value, run.error
            answer = run.output["structured"]
            if fmt == "csv":
                assert answer["rows"] == [
                    {"name": "Ada", "score": "9", "extra": ""},
                    {"name": "Linus", "score": "", "extra": "true"},
                ]
            elif fmt == "json":
                assert answer["json_value"] == {"leads": [1, 2]}
            else:
                assert answer["text"] == "Zażółć gęślą jaźń"

    async def test_a_write_with_nothing_bound_or_an_unwritable_cell_fails(self, engine):
        for config, bindings in [
            ({"format": "csv"}, []),
            ({"format": "json"}, []),
            ({"format": "csv"}, [("rows", [{"a": {"nested": 1}}])]),
        ]:
            write = _node("file.write", config)
            graph = _chain(write, bindings=[_literal(write, f, v) for f, v in bindings])
            seeded = await seed_run(engine, graph)
            await drive(seeded)
            assert (await _error(seeded))["code"] == "FILE_WRITE_FAILED"

    async def test_a_write_over_the_limit_stores_nothing(self, engine, monkeypatch):
        from app.workflows.nodes.file_write import _handler

        monkeypatch.setattr(_handler, "MAX_WRITE_BYTES", 3)
        write = _node("file.write")
        seeded = await seed_run(engine, _chain(write, bindings=[_literal(write, "text", "four")]))
        await drive(seeded)
        assert (await _error(seeded))["code"] == files.FILE_TOO_LARGE
        async with seeded.factory() as db:
            assert (await db.execute(select(WorkflowFile))).scalars().all() == []

    @pytest.mark.parametrize(
        ("data", "parse_as"),
        [(b"\xff\xfe", "text"), (b"{not json", "json"), (b"a,b\n1,2,3\n", "csv")],
        ids=["not-utf8", "bad-json", "ragged-csv"],
    )
    async def test_a_file_that_is_not_what_it_is_read_as_fails_whole(
        self, engine, storage, data, parse_as
    ):
        _run, seeded = await _run_on(
            engine,
            storage,
            _one_step("file.read", {"parse_as": parse_as}),
            data,
            content_type="text/plain",
        )
        assert (await _error(seeded))["code"] == "FILE_PARSE_FAILED"

    async def test_a_file_over_the_limit_is_refused_before_it_is_read(self, engine, storage):
        _run, seeded = await _run_on(
            engine,
            storage,
            _one_step("file.read", {"max_bytes": 3}),
            b"four",
            content_type="text/plain",
        )
        error = await _error(seeded)
        assert error["code"] == files.FILE_TOO_LARGE
        assert error["details"] == {"byte_size": 4, "max_bytes": 3}

    async def test_an_empty_csv_has_no_rows_and_a_blank_line_is_skipped(self, engine, storage):
        for data, rows in [(b"", []), (b"a\n1\n\n2\n", [{"a": "1"}, {"a": "2"}])]:
            run, _seeded = await _run_on(
                engine,
                storage,
                _one_step("file.read", {"parse_as": "csv"}),
                data,
                content_type="text/csv",
            )
            assert run.output["structured"]["rows"] == rows

    async def test_a_csv_header_naming_a_column_twice_is_refused(self, engine, storage):
        _run, seeded = await _run_on(
            engine,
            storage,
            _one_step("file.read", {"parse_as": "csv"}),
            b"a,a\n1,2\n",
            content_type="text/csv",
        )
        assert (await _error(seeded))["code"] == "FILE_PARSE_FAILED"


class TestWhoMayReadAFile:
    @pytest.mark.security
    async def test_another_organizations_file_is_not_found(self, engine, storage):
        other = await seed_run(engine, _chain(_node("debug.echo"), bindings=[]))
        foreign = await _stored(engine, storage, other.run, b"secret", content_type="text/plain")
        read = _node("file.read")
        graph = _chain(read, bindings=[_literal(read, "file", foreign.model_dump(mode="json"))])
        seeded = await seed_run(engine, graph)
        await drive(seeded)
        assert (await _error(seeded))["code"] == files.FILE_NOT_FOUND

    @pytest.mark.security
    async def test_another_runs_file_is_not_found_until_the_run_is_started_with_it(
        self, engine, storage
    ):
        member = await _member(engine)
        earlier = await seed_run(engine, _chain(_node("debug.echo"), bindings=[]), member=member)
        theirs = await _stored(engine, storage, earlier.run, b"hello", content_type="text/plain")
        read = _node("file.read")
        graph = _chain(read, bindings=[_literal(read, "file", theirs.model_dump(mode="json"))])

        refused = await seed_run(engine, graph, member=member)
        await drive(refused)
        assert (await _error(refused))["code"] == files.FILE_NOT_FOUND

        imported = await seed_run(engine, graph, member=member)
        async with imported.factory() as db:
            db.add(
                ResourceRef(
                    organization_id=imported.org.id,
                    workflow_run_id=imported.run.id,
                    kind="file",
                    ref=theirs.model_dump(mode="json"),
                )
            )
            await db.commit()
        run = await drive(imported)
        assert run.output["structured"]["text"] == "hello"

    async def test_a_file_whose_bytes_are_gone_is_not_found(self, engine, storage):
        seeded_file: dict[str, Any] = {}

        def graph_for(ref: FileRef) -> WorkflowGraph:
            seeded_file["ref"] = ref
            return _one_step("file.read")(ref)

        async def gone(*_args: Any, **_kwargs: Any) -> bytes:
            raise FileNotFoundError

        with patch.object(storage, "load", new=gone):
            _run, seeded = await _run_on(
                engine, storage, graph_for, b"x", content_type="text/plain"
            )
        assert (await _error(seeded))["code"] == files.FILE_NOT_FOUND

    @pytest.mark.security
    async def test_publishing_refuses_a_file_from_a_run_the_author_cannot_see(
        self, engine, storage
    ):
        member = await _member(engine)
        mine = await seed_run(engine, _chain(_node("debug.echo"), bindings=[]), member=member)
        ref = await _stored(engine, storage, mine.run, b"x", content_type="text/plain")
        read = _node("file.read")
        # A file is named in a graph as a `FileRef` source - what admission imports.
        graph = _chain(
            read, bindings=[Binding(target_node_id=read.id, target_field="file", source=ref)]
        )
        stranger, _org = await _member(engine)
        async with mine.factory() as db:
            await validate_graph(db, mine.ctx, graph)

            # A viewer of the same organization who cannot see the private
            # workflow whose run made the file.
            viewer = AuthContext(user_id=stranger.id, organization_id=mine.org.id, role="viewer")
            with pytest.raises(GraphValidationError, match="not accessible"):
                await validate_graph(db, viewer, graph)

            missing = FileRef(file_id=uuid.uuid4(), content_type="text/plain", byte_size=1)
            gone = _chain(
                read,
                bindings=[Binding(target_node_id=read.id, target_field="file", source=missing)],
            )
            with pytest.raises(GraphValidationError, match="not accessible"):
                await validate_graph(db, mine.ctx, gone)


def _pdf(*pages: str | None) -> bytes:
    """A PDF with one page per entry: text, or `None` for a scanned (image-only) page."""
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        if text is None:
            png = io.BytesIO()
            Image.new("RGB", (20, 20), "white").save(png, format="PNG")
            page.insert_image(page.rect, stream=png.getvalue())
        else:
            page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def _zip(members: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return out.getvalue()


def _docx(*paragraphs: str) -> bytes:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


class TestExtractingText:
    async def test_every_supported_format_gives_its_text(self, engine, storage):
        for data, content_type, fmt, text, pages in [
            (b"plain words", "text/plain", "txt", "plain words", None),
            (b'{"a": 1}', "application/json", "json", '{"a": 1}', None),
            (b"a,b\n1,2\n", "text/csv", "csv", "a,b\n1,2\n", None),
            (_pdf("First page", "Second page"), "application/pdf", "pdf", None, 2),
            (_docx("Hello", "World"), files.DOCX, "docx", "Hello\nWorld", None),
        ]:
            run, _seeded = await _run_on(
                engine, storage, _one_step("text.extract"), data, content_type=content_type
            )
            answer = run.output["structured"]
            assert answer["source_format"] == fmt
            assert answer["page_count"] == pages
            if text is not None:
                assert answer["text"] == text
            else:
                assert "First page" in answer["text"] and "Second page" in answer["text"]

    async def test_a_scanned_page_is_named_rather_than_read_as_nothing(self, engine, storage):
        _run, seeded = await _run_on(
            engine,
            storage,
            _one_step("text.extract"),
            _pdf("Cover", None),
            content_type="application/pdf",
        )
        error = await _error(seeded)
        assert error["code"] == "TEXT_EXTRACTION_NEEDS_OCR"
        assert error["details"] == {"page_numbers": [2]}

    async def test_encrypted_corrupt_and_unsupported_documents_fail_with_their_own_code(
        self, engine, storage
    ):
        document = pymupdf.open()
        document.new_page().insert_text((72, 72), "hidden")
        encrypted = document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw")
        document.close()
        for data, content_type, code in [
            (encrypted, "application/pdf", "DOCUMENT_ENCRYPTED"),
            (b"%PDF-1.7 truncated", "application/pdf", "DOCUMENT_CORRUPT"),
            (b"PK\x03\x04 broken", files.DOCX, "DOCUMENT_CORRUPT"),
            # A sound ZIP that is not a Word document: python-docx refuses it.
            (_zip({"notes.txt": b"hello"}), files.DOCX, "DOCUMENT_CORRUPT"),
            (b"\xff\xfe", "text/plain", "DOCUMENT_CORRUPT"),
            (b"\x89PNG\r\n\x1a\n", "image/png", "UNSUPPORTED_FORMAT"),
        ]:
            _run, seeded = await _run_on(
                engine, storage, _one_step("text.extract"), data, content_type=content_type
            )
            assert (await _error(seeded))["code"] == code, content_type

    async def test_a_docx_that_unpacks_past_the_archive_bound_is_refused_before_parsing(
        self, engine, storage, monkeypatch
    ):
        """A small file can hold a huge compressed part: the member bound a chat
        upload has is applied before python-docx expands any of it."""
        monkeypatch.setattr(settings, "CHAT_ARCHIVE_MEMBER_MAX_BYTES", 64 * 1024)
        # Highly compressible: well under a kilobyte on disk, a megabyte unpacked.
        data = _docx("A" * 1_000_000)
        assert len(data) < 64 * 1024
        _run, seeded = await _run_on(
            engine, storage, _one_step("text.extract"), data, content_type=files.DOCX
        )
        assert (await _error(seeded))["code"] == "DOCUMENT_TOO_LARGE"

    async def test_text_over_the_limit_is_refused_and_a_big_file_before_reading(
        self, engine, storage
    ):
        for config, code in [
            ({"max_chars": 3}, "TEXT_TOO_LONG"),
            ({"max_bytes": 2}, "FILE_TOO_LARGE"),
        ]:
            _run, seeded = await _run_on(
                engine,
                storage,
                _one_step("text.extract", config),
                b"four",
                content_type="text/plain",
            )
            assert (await _error(seeded))["code"] == code


class TestConverting:
    async def test_csv_and_json_convert_both_ways(self, engine, storage):
        run, seeded = await _run_on(
            engine,
            storage,
            _one_step("convert.csv_to_json"),
            b"a,b\n1,2\n",
            content_type="text/csv",
            filename="leads.csv",
        )
        answer = run.output["structured"]
        assert answer["row_count"] == 1
        assert json.loads(await _saved(seeded, answer["file"])) == [{"a": "1", "b": "2"}]

        run, seeded = await _run_on(
            engine,
            storage,
            _one_step("convert.json_to_csv"),
            b'[{"a": 1}, {"b": null}]',
            content_type="application/json",
        )
        answer = run.output["structured"]
        assert answer["row_count"] == 2
        assert (await _saved(seeded, answer["file"])).decode() == "a,b\n1,\n,\n"

    @pytest.mark.parametrize(
        ("data", "code"),
        [
            (b'{"a": 1}', "NOT_TABULAR"),
            (b'[{"a": {"b": 1}}]', "NOT_TABULAR"),
            (b"not json", "FILE_PARSE_FAILED"),
        ],
        ids=["an-object", "a-nested-cell", "not-json"],
    )
    async def test_json_that_is_not_a_table_is_refused(self, engine, storage, data, code):
        _run, seeded = await _run_on(
            engine,
            storage,
            _one_step("convert.json_to_csv"),
            data,
            content_type="application/json",
        )
        assert (await _error(seeded))["code"] == code

    async def test_a_csv_it_cannot_read_is_refused(self, engine, storage):
        _run, seeded = await _run_on(
            engine, storage, _one_step("convert.csv_to_json"), b"a\n1,2\n", content_type="text/csv"
        )
        assert (await _error(seeded))["code"] == "FILE_PARSE_FAILED"

    async def test_text_becomes_a_file(self, engine):
        step = _node("convert.text_to_file", {"filename": "notes.txt"})
        seeded = await seed_run(engine, _chain(step, bindings=[_literal(step, "text", "hello")]))
        run = await drive(seeded)
        assert await _saved(seeded, run.output["structured"]["file"]) == b"hello"

    async def test_chosen_pages_render_as_png_within_the_limit(self, engine, storage, monkeypatch):
        run, seeded = await _run_on(
            engine,
            storage,
            _one_step("convert.pdf_to_png", {"pages": [2], "dpi": 72}),
            _pdf("one", "two"),
            content_type="application/pdf",
            filename="deck.pdf",
        )
        (image,) = run.output["structured"]["images"]
        assert image["page"] == 2 and image["file"]["content_type"] == "image/png"
        assert (await _saved(seeded, image["file"])).startswith(b"\x89PNG")

        monkeypatch.setattr(settings, "CHAT_IMAGE_MAX_PIXELS", 100)
        for config, data, content_type, code in [
            ({"pages": [1]}, _pdf("one"), "application/pdf", "IMAGE_TOO_LARGE"),
            ({"pages": [3]}, _pdf("one"), "application/pdf", "PAGE_OUT_OF_RANGE"),
            ({}, b"hello", "text/plain", "UNSUPPORTED_FORMAT"),
            ({}, b"%PDF-1.7 truncated", "application/pdf", "DOCUMENT_CORRUPT"),
        ]:
            _run, seeded = await _run_on(
                engine,
                storage,
                _one_step("convert.pdf_to_png", config),
                data,
                content_type=content_type,
            )
            assert (await _error(seeded))["code"] == code

    async def test_an_encrypted_pdf_does_not_render(self, engine, storage):
        document = pymupdf.open()
        document.new_page()
        encrypted = document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw")
        document.close()
        _run, seeded = await _run_on(
            engine,
            storage,
            _one_step("convert.pdf_to_png"),
            encrypted,
            content_type="application/pdf",
        )
        assert (await _error(seeded))["code"] == "DOCUMENT_ENCRYPTED"


def _image(size: tuple[int, int], *, mode: str = "RGB", fmt: str = "PNG", **save: Any) -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, "red").save(out, format=fmt, **save)
    return out.getvalue()


async def _image_of(seeded: SeededRun, ref: dict[str, Any]) -> Image.Image:
    return Image.open(io.BytesIO(await _saved(seeded, ref)))


class TestTransformingImages:
    async def test_crop_resize_and_rotate_run_in_order(self, engine, storage):
        config = {
            "crop": {"left": 0, "top": 0, "width": 40, "height": 20},
            "resize": {"width": 20, "height": 20, "mode": "fit"},
            "rotate_degrees": 90,
            "output_format": "webp",
        }
        run, seeded = await _run_on(
            engine,
            storage,
            _one_step("image.transform", config),
            _image((50, 30)),
            content_type="image/png",
            filename="photo.png",
        )
        answer = run.output["structured"]
        # 40x20 cropped, fitted into 20x20 as 20x10, then turned on its side.
        assert (answer["width"], answer["height"]) == (10, 20)
        assert answer["content_type"] == "image/webp"
        assert (await _image_of(seeded, answer["file"])).format == "WEBP"

    async def test_fill_covers_the_box_and_exact_stretches_to_it(self, engine, storage):
        for mode in ("fill", "exact"):
            run, _seeded = await _run_on(
                engine,
                storage,
                _one_step("image.transform", {"resize": {"width": 8, "height": 4, "mode": mode}}),
                _image((30, 30)),
                content_type="image/png",
            )
            assert (run.output["structured"]["width"], run.output["structured"]["height"]) == (8, 4)

    async def test_a_jpeg_carries_no_metadata_and_an_rgba_source_converts(self, engine, storage):
        exif = Image.Exif()
        exif[0x010F] = "Camera maker"
        run, seeded = await _run_on(
            engine,
            storage,
            _one_step("image.transform", {"output_format": "jpeg", "rotate_degrees": 180}),
            _image((10, 10), mode="RGBA", fmt="PNG", exif=exif.tobytes()),
            content_type="image/png",
        )
        result = await _image_of(seeded, run.output["structured"]["file"])
        assert result.format == "JPEG" and result.mode == "RGB"
        assert not result.getexif() and "icc_profile" not in result.info

    async def test_an_image_bigger_than_the_limit_is_refused_before_it_is_decoded(
        self, engine, storage, monkeypatch
    ):
        monkeypatch.setattr(settings, "CHAT_IMAGE_MAX_PIXELS", 100)
        for config, size, code in [
            ({}, (20, 20), "IMAGE_TOO_LARGE"),
            ({"resize": {"width": 50, "height": 50}}, (5, 5), "IMAGE_TOO_LARGE"),
            (
                {"crop": {"left": 2, "top": 2, "width": 5, "height": 5}},
                (5, 5),
                "CROP_OUT_OF_BOUNDS",
            ),
        ]:
            _run, seeded = await _run_on(
                engine,
                storage,
                _one_step("image.transform", config),
                _image(size),
                content_type="image/png",
            )
            assert (await _error(seeded))["code"] == code

    async def test_a_decompression_bomb_corrupt_and_unsupported_images_fail(
        self, engine, storage, monkeypatch
    ):
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
        _run, seeded = await _run_on(
            engine,
            storage,
            _one_step("image.transform"),
            _image((20, 20)),
            content_type="image/png",
        )
        assert (await _error(seeded))["code"] == "IMAGE_TOO_LARGE"
        monkeypatch.undo()

        for data, content_type, code in [
            (b"\x89PNG\r\n\x1a\nnot really", "image/png", "IMAGE_CORRUPT"),
            (b"hello", "text/plain", "UNSUPPORTED_FORMAT"),
        ]:
            _run, seeded = await _run_on(
                engine, storage, _one_step("image.transform"), data, content_type=content_type
            )
            assert (await _error(seeded))["code"] == code

    async def test_pixels_that_cannot_be_decoded_are_corrupt(self, engine, storage):
        noisy = Image.frombytes("RGB", (200, 200), bytes((i * 7) % 256 for i in range(120_000)))
        out = io.BytesIO()
        noisy.save(out, format="JPEG")
        whole = out.getvalue()
        _run, seeded = await _run_on(
            engine,
            storage,
            _one_step("image.transform"),
            whole[: len(whole) // 2],
            content_type="image/jpeg",
        )
        assert (await _error(seeded))["code"] == "IMAGE_CORRUPT"


class TestAStepGivenNothing:
    async def test_every_file_step_without_its_file_says_it_is_not_configured(self):
        from app.workflows.nodes.convert_csv_to_json import _handler as csv_to_json
        from app.workflows.nodes.convert_json_to_csv import _handler as json_to_csv
        from app.workflows.nodes.convert_pdf_to_png import _handler as pdf_to_png
        from app.workflows.nodes.convert_text_to_file import _handler as text_to_file
        from app.workflows.nodes.file_read import _handler as file_read
        from app.workflows.nodes.file_write import _handler as file_write
        from app.workflows.nodes.image_transform import _handler as image_transform
        from app.workflows.nodes.text_extract import _handler as text_extract

        for module in (
            csv_to_json,
            json_to_csv,
            pdf_to_png,
            text_to_file,
            file_read,
            file_write,
            image_transform,
            text_extract,
        ):
            result = await module.handle(None, None)
            assert result.error.code == "FILE_STEP_NOT_CONFIGURED", module.__name__

    async def test_a_file_whose_row_cannot_be_written_leaves_no_bytes(self, engine, storage):
        write = _node("file.write")
        seeded = await seed_run(engine, _chain(write, bindings=[_literal(write, "text", "hi")]))
        with patch.object(
            files.workflow_file_repo, "create", side_effect=RuntimeError("insert failed")
        ):
            run = await drive(seeded)
        # An unexpected failure is retried; what matters is that the attempt that
        # failed left nothing stored behind it.
        assert run.status == WorkflowRunStatus.WAITING_RETRY.value
        assert not any(path.is_file() for path in Path(storage.base_dir).rglob("*"))


class TestAFileTheRunWasNotGiven:
    @pytest.mark.security
    @pytest.mark.parametrize(
        "definition_id",
        [
            "convert.csv_to_json",
            "convert.json_to_csv",
            "convert.pdf_to_png",
            "image.transform",
            "text.extract",
        ],
    )
    async def test_every_file_step_refuses_it_as_not_found(self, engine, storage, definition_id):
        earlier = await seed_run(engine, _chain(_node("debug.echo"), bindings=[]))
        foreign = await _stored(engine, storage, earlier.run, b"x", content_type="text/plain")
        seeded = await seed_run(engine, _one_step(definition_id)(foreign))
        await drive(seeded)
        assert (await _error(seeded))["code"] == files.FILE_NOT_FOUND


class TestSniffing:
    def test_bytes_say_what_they_are(self):
        assert files.sniff(_image((1, 1))) == "image/png"
        assert files.sniff(b"%PDF-1.7") == "application/pdf"
        assert files.sniff(_docx("x")) == files.DOCX
        assert files.sniff(b"PK\x03\x04" + b"\x00" * 30) == "application/zip"
        assert files.sniff(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") == "application/octet-stream"
        assert files.sniff(b"\xff\xfe\xfd") == "application/octet-stream"
        assert files.sniff(b'{"a": 1}') == "application/json"
        assert files.sniff(b"hello") == "text/plain"

    def test_a_zip_that_is_not_one_is_just_a_zip(self):
        assert files._is_docx(b"PK\x03\x04 not a real archive") is False
