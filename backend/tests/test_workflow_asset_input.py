"""The media Asset node retains run-file authority and refuses forged metadata."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.services.media_inspection import MediaInfo, MediaInspectionError
from app.workflows import files
from app.workflows._registry import get
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed
from app.workflows.nodes.asset_input import _handler as asset

pytestmark = pytest.mark.anyio


@pytest.fixture
def reference():
    return FileRef(file_id=uuid4(), content_type="image/png", byte_size=4)


@pytest.fixture
def enabled(monkeypatch, reference):
    monkeypatch.setattr(settings, "WORKFLOW_ASSET_INPUT_ENABLED", True)
    load = AsyncMock(return_value=files.StoredFile(b"data", "image/png", "private.png"))
    inspect = AsyncMock(
        return_value=MediaInfo(kind="image", media_type="image/png", byte_size=4, width=2, height=2)
    )
    monkeypatch.setattr(asset.files, "load_verified", load)
    monkeypatch.setattr(asset, "inspect_media", inspect)
    return load, inspect


async def test_success_keeps_the_authorized_reference_and_detected_metadata(enabled, reference):
    result = await asset.handle(asset.AssetInputConfig(), asset.AssetInput(file=reference))
    assert isinstance(result, Completed)
    assert result.output.file == reference
    assert result.output.kind == "image" and result.output.width == 2
    enabled[0].assert_awaited_once_with(reference, max_bytes=50_000_000)
    assert enabled[1].await_args.kwargs["expected_type"] == "image/png"


@pytest.mark.security
async def test_disabled_definition_remains_readable_and_never_reads_a_file(
    monkeypatch, enabled, reference
):
    monkeypatch.setattr(settings, "WORKFLOW_ASSET_INPUT_ENABLED", False)
    definition = get("asset.input", 1)
    assert definition.output_schema is asset.AssetOutput
    assert definition.available() is False
    assert await asset.check_resources(None, None, asset.AssetInputConfig())
    result = await asset.handle(asset.AssetInputConfig(), asset.AssetInput(file=reference))
    assert result.error.code == "MEDIA_DISABLED"
    enabled[0].assert_not_awaited()
    enabled[1].assert_not_awaited()


async def test_enabled_resource_check_accepts_only_the_deployment_capability(enabled):
    assert await asset.check_resources(None, None, asset.AssetInputConfig()) == []


@pytest.mark.parametrize("config,payload", [(None, None), (asset.AssetInputConfig(), None)])
async def test_unconfigured_node_returns_a_typed_failure(enabled, config, payload):
    result = await asset.handle(config, payload)
    assert result.error.code == "FILE_STEP_NOT_CONFIGURED"


def test_config_is_closed_and_rejects_duplicate_kinds():
    with pytest.raises(ValidationError):
        asset.AssetInputConfig(url="https://example.com/private")
    with pytest.raises(ValidationError):
        asset.AssetInputConfig(accepted_kinds=["image", "image"])


@pytest.mark.parametrize("supplied", [None, {}, "https://example.com/private"])
async def test_required_run_input_is_not_a_url_or_an_invented_reference(
    monkeypatch, enabled, reference, supplied
):
    monkeypatch.setattr(
        asset.context, "current", lambda: SimpleNamespace(run_input={"photo": supplied})
    )
    result = await asset.handle(
        asset.AssetInputConfig(required_input_name="photo"), asset.AssetInput(file=reference)
    )
    assert result.error.code == "MEDIA_INPUT_REQUIRED"
    enabled[0].assert_not_awaited()


async def test_required_run_input_must_be_the_same_file(monkeypatch, enabled, reference):
    other = reference.model_copy(update={"file_id": uuid4()})
    monkeypatch.setattr(
        asset.context,
        "current",
        lambda: SimpleNamespace(run_input={"photo": other.model_dump(mode="json")}),
    )
    result = await asset.handle(
        asset.AssetInputConfig(required_input_name="photo"), asset.AssetInput(file=reference)
    )
    assert result.error.code == "MEDIA_INPUT_REQUIRED"
    enabled[0].assert_not_awaited()


async def test_named_input_and_allowed_media_kind_are_checked(monkeypatch, enabled, reference):
    monkeypatch.setattr(
        asset.context,
        "current",
        lambda: SimpleNamespace(run_input={"photo": reference.model_dump(mode="json")}),
    )
    result = await asset.handle(
        asset.AssetInputConfig(required_input_name="photo", accepted_kinds=["video"]),
        asset.AssetInput(file=reference),
    )
    assert result.error.code == "MEDIA_KIND_REFUSED"


@pytest.mark.parametrize(
    "error,code",
    [
        (MediaInspectionError("MEDIA_INVALID", "Invalid media"), "MEDIA_INVALID"),
        (TimeoutError(), "MEDIA_INSPECTION_TIMEOUT"),
    ],
)
async def test_inspection_failures_stay_typed_and_do_not_publish_output(
    enabled, reference, error, code
):
    enabled[1].side_effect = error
    result = await asset.handle(asset.AssetInputConfig(), asset.AssetInput(file=reference))
    assert isinstance(result, Failed) and result.error.code == code


async def test_missing_source_preserves_the_file_boundary_refusal(enabled, reference):
    enabled[0].return_value = files.not_found()
    result = await asset.handle(asset.AssetInputConfig(), asset.AssetInput(file=reference))
    assert result.error.code == "FILE_NOT_FOUND"
    enabled[1].assert_not_awaited()


@pytest.fixture
def stored(monkeypatch, reference):
    row = SimpleNamespace(
        byte_size=4, content_type="image/png", filename="private.png", storage_path="owned-object"
    )
    lookup = AsyncMock(return_value=row)
    closed = []

    async def chunks():
        try:
            yield b"da"
            yield b"ta"
        finally:
            closed.append(True)

    storage = SimpleNamespace(open_stream=AsyncMock(side_effect=lambda _path: chunks()))
    monkeypatch.setattr(files, "_row_for", lookup)
    monkeypatch.setattr(files, "get_file_storage", lambda: storage)
    return row, lookup, storage, closed


async def test_verified_read_checks_actual_stream_size_and_closes_it(stored, reference):
    result = await files.load_verified(reference, max_bytes=4)
    assert result.data == b"data" and result.content_type == "image/png"
    assert stored[3] == [True]
    stored[1].assert_awaited_once_with(reference)


@pytest.mark.security
@pytest.mark.parametrize("change", [{"byte_size": 3}, {"content_type": "image/jpeg"}])
async def test_forged_metadata_cannot_open_storage(stored, reference, change):
    result = await files.load_verified(reference.model_copy(update=change), max_bytes=100)
    assert result.error.code == "FILE_METADATA_MISMATCH"
    stored[2].open_stream.assert_not_awaited()


@pytest.mark.security
async def test_a_refused_run_file_never_opens_storage(stored, reference):
    stored[1].return_value = None
    result = await files.load_verified(reference, max_bytes=100)
    assert result.error.code == "FILE_NOT_FOUND"
    stored[2].open_stream.assert_not_awaited()


async def test_oversize_row_is_refused_before_storage(stored, reference):
    result = await files.load_verified(reference, max_bytes=3)
    assert result.error.code == "FILE_TOO_LARGE"
    stored[2].open_stream.assert_not_awaited()


@pytest.mark.security
async def test_actual_bytes_cannot_bypass_a_small_row_size(stored, reference):
    stored[0].byte_size = 2
    result = await files.load_verified(reference.model_copy(update={"byte_size": 2}), max_bytes=3)
    assert result.error.code == "FILE_TOO_LARGE" and stored[3] == [True]


async def test_actual_size_mismatch_is_refused(stored, reference):
    stored[0].byte_size = 5
    result = await files.load_verified(reference.model_copy(update={"byte_size": 5}), max_bytes=10)
    assert result.error.code == "FILE_METADATA_MISMATCH" and stored[3] == [True]


async def test_deleted_storage_object_is_the_same_not_found(stored, reference):
    stored[2].open_stream.side_effect = FileNotFoundError()
    result = await files.load_verified(reference, max_bytes=10)
    assert result.error.code == "FILE_NOT_FOUND"


async def test_object_disappearing_midstream_is_closed_and_not_found(stored, reference):
    closed = []

    async def missing():
        try:
            yield b"da"
            raise FileNotFoundError("private storage path")
        finally:
            closed.append(True)

    stored[2].open_stream.side_effect = lambda _path: missing()
    result = await files.load_verified(reference, max_bytes=4)
    assert result.error.code == "FILE_NOT_FOUND" and closed == [True]
    assert "private storage" not in result.model_dump_json()


async def test_storage_iterator_without_an_optional_close_method_is_supported(stored, reference):
    class Chunks:
        def __init__(self):
            self.parts = iter([b"da", b"ta"])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.parts)
            except StopIteration:
                raise StopAsyncIteration from None

    stored[2].open_stream.side_effect = lambda _path: Chunks()
    result = await files.load_verified(reference, max_bytes=4)
    assert result.data == b"data"


def test_workflow_file_sniffer_labels_media_before_generic_text_or_container_types():
    assert files.sniff(b"RIFF\0\0\0\0WAVE") == "audio/wav"
    assert files.sniff(b"\0\0\0\x14ftypisom\0\0\0\0mp42") == "video/mp4"
