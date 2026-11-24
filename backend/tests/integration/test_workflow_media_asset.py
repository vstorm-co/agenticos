"""The Asset node reads real media only through the executing run's file authority."""

import io
import uuid
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.db.models.workflow_file import WorkflowFile
from app.db.models.workflow_run import ResourceRef
from app.services.file_storage import LocalFileStorage
from app.workflows.contracts.io import Binding, FileRef, LiteralValue, NodeOutputRef
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import drive, seed_run

pytestmark = pytest.mark.anyio


@pytest.fixture
def media_storage(monkeypatch, tmp_path):
    storage = LocalFileStorage(tmp_path)
    monkeypatch.setattr("app.workflows.files.get_file_storage", lambda: storage)
    monkeypatch.setattr(settings, "WORKFLOW_ASSET_INPUT_ENABLED", True)
    return storage


def graph_for(ref, **config):
    entry, asset, output = (
        NodeInstance(
            id=uuid.uuid4(),
            definition_id=kind,
            definition_version=1,
            config=config if kind == "asset.input" else {},
            layout=NodePosition(x=0, y=0),
        )
        for kind in ("core.input", "asset.input", "core.output")
    )
    return WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, asset, output),
        edges=tuple(
            Edge(
                id=uuid.uuid4(),
                source_node_id=a.id,
                source_port="out",
                target_node_id=b.id,
                target_port="in",
            )
            for a, b in ((entry, asset), (asset, output))
        ),
        bindings=(
            Binding(
                target_node_id=asset.id,
                target_field="file",
                source=LiteralValue(value=ref.model_dump(mode="json")),
            ),
            Binding(
                target_node_id=output.id,
                target_field="structured",
                source=NodeOutputRef(node_id=asset.id, port="out"),
            ),
        ),
    )


async def producer(engine, storage):
    placeholder = FileRef(file_id=uuid.uuid4(), content_type="image/png", byte_size=1)
    seeded = await seed_run(engine, graph_for(placeholder))
    image = io.BytesIO()
    Image.new("RGB", (12, 8), "blue").save(image, format="PNG")
    data = image.getvalue()
    ref = FileRef(file_id=uuid.uuid4(), content_type="image/png", byte_size=len(data))
    path = f"workflow-files/{seeded.org.id}/{seeded.run.id}/{ref.file_id}"
    await storage.save_at(path, data)
    async with async_sessionmaker(engine)() as db:
        db.add(
            WorkflowFile(
                id=ref.file_id,
                organization_id=seeded.org.id,
                workflow_run_id=seeded.run.id,
                storage_path=path,
                content_type=ref.content_type,
                byte_size=len(data),
                filename="sample.png",
            )
        )
        await db.commit()
    return seeded, ref, path


async def import_file(seeded, ref):
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


async def test_owned_import_is_decoded_and_returns_the_same_durable_file(engine, media_storage):
    earlier, ref, _path = await producer(engine, media_storage)
    consumer = await seed_run(
        engine,
        graph_for(ref, required_input_name="photo"),
        member=(earlier.principal, earlier.org),
        run_input={"photo": ref.model_dump(mode="json")},
    )
    await import_file(consumer, ref)
    result = await drive(consumer)
    assert result.status == "succeeded", result.error
    assert result.output["structured"] == {
        "file": ref.model_dump(mode="json"),
        "kind": "image",
        "media_type": "image/png",
        "byte_size": ref.byte_size,
        "width": 12,
        "height": 8,
        "duration_seconds": None,
    }


@pytest.mark.security
@pytest.mark.parametrize("boundary", ["other_org", "other_run", "deleted_row", "revoked_import"])
async def test_inaccessible_or_expired_media_never_opens_storage(
    engine, media_storage, monkeypatch, boundary
):
    earlier, ref, _path = await producer(engine, media_storage)
    member = None if boundary == "other_org" else (earlier.principal, earlier.org)
    consumer = await seed_run(engine, graph_for(ref), member=member)
    if boundary in {"other_org", "deleted_row", "revoked_import"}:
        await import_file(consumer, ref)
    async with consumer.factory() as db:
        if boundary == "deleted_row":
            await db.delete(await db.get(WorkflowFile, ref.file_id))
        if boundary == "revoked_import":
            from sqlalchemy import delete

            await db.execute(
                delete(ResourceRef).where(ResourceRef.workflow_run_id == consumer.run.id)
            )
        await db.commit()
    opened = AsyncMock(wraps=media_storage.open_stream)
    monkeypatch.setattr(media_storage, "open_stream", opened)
    result = await drive(consumer)
    assert result.status == "failed" and result.error["code"] == "FILE_NOT_FOUND"
    opened.assert_not_awaited()


@pytest.mark.security
async def test_forged_metadata_refuses_before_read_even_with_an_admitted_file(
    engine, media_storage, monkeypatch
):
    earlier, ref, _path = await producer(engine, media_storage)
    forged = ref.model_copy(update={"content_type": "video/mp4"})
    consumer = await seed_run(engine, graph_for(forged), member=(earlier.principal, earlier.org))
    await import_file(consumer, ref)
    opened = AsyncMock(wraps=media_storage.open_stream)
    monkeypatch.setattr(media_storage, "open_stream", opened)
    result = await drive(consumer)
    assert result.status == "failed" and result.error["code"] == "FILE_METADATA_MISMATCH"
    opened.assert_not_awaited()


async def test_missing_stored_object_returns_the_same_not_found(engine, media_storage):
    earlier, ref, path = await producer(engine, media_storage)
    consumer = await seed_run(engine, graph_for(ref), member=(earlier.principal, earlier.org))
    await import_file(consumer, ref)
    await media_storage.delete(path)
    result = await drive(consumer)
    assert result.status == "failed" and result.error["code"] == "FILE_NOT_FOUND"


async def test_feature_disable_refuses_new_execution_without_deleting_existing_media(
    engine, media_storage, monkeypatch
):
    earlier, ref, path = await producer(engine, media_storage)
    consumer = await seed_run(engine, graph_for(ref), member=(earlier.principal, earlier.org))
    await import_file(consumer, ref)
    monkeypatch.setattr(settings, "WORKFLOW_ASSET_INPUT_ENABLED", False)
    opened = AsyncMock(wraps=media_storage.open_stream)
    monkeypatch.setattr(media_storage, "open_stream", opened)
    result = await drive(consumer)
    assert result.status == "failed" and result.error["code"] == "MEDIA_DISABLED"
    opened.assert_not_awaited()
    assert len(await media_storage.load(path)) == ref.byte_size
