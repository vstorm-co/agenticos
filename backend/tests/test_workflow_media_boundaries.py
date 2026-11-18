"""Media refusal, bounded recovery and fee evidence never grant a fresh effect."""

import asyncio
import hashlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic_ai.messages import BinaryImage

from app.core.exceptions import BadRequestError
from app.schemas.workflow_media import VideoMediaEstimateRequest
from app.services import image_models
from app.services.media_inspection import MediaInfo
from app.services.organization_secret import OrganizationSecretService
from app.services.video_generation import Clip
from app.services.workflow_media import _admission, _execution, _output, _pricing
from app.services.workflow_media._errors import MediaOperationError
from app.services.workflow_media_read import WorkflowMediaReadService
from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Failed, Uncertain
from app.workflows.nodes._media_config import MediaGenerateInput
from tests.integration.workflow_media_runtime_support import png_bytes
from tests.test_workflow_media_runtime import image_config, video_config

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def operation(config=None, **changes):
    config = config or image_config()
    data = b"synthetic"
    metadata = MediaInfo(
        kind="image", media_type="image/png", byte_size=len(data), width=1, height=1
    )
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        workflow_run_id=uuid4(),
        output_file_id=uuid4(),
        pricing_snapshot=_pricing.snapshot(config).model_dump(mode="json"),
        media_kind="image",
        provider_receipt=None,
        output_sha256=hashlib.sha256(data).hexdigest(),
        output_metadata=metadata.model_dump(mode="json"),
        reserved_bytes=len(data),
        **changes,
    )


def reference():
    data = png_bytes()
    return data, FileRef(file_id=uuid4(), content_type="image/png", byte_size=len(data))


def google_config():
    selected = next(
        model
        for provider in image_models.image_providers()
        if provider.provider == "google"
        for model in provider.models
        if model.workflow is not None and model.workflow.reference_image
    )
    return image_config(provider="google", model=selected.id)


async def test_an_unsupported_reference_refuses_before_file_access_or_admission(monkeypatch):
    _data, ref = reference()
    load = AsyncMock()
    admit = AsyncMock()
    monkeypatch.setattr(files, "load_verified", load)
    monkeypatch.setattr(_execution, "admit", admit)
    result = await _execution.generate(
        image_config(), MediaGenerateInput(prompt="Synthetic", reference_image=ref)
    )
    assert isinstance(result, Failed) and result.error.code == "MEDIA_REFERENCE_REFUSED"
    load.assert_not_awaited()
    admit.assert_not_awaited()


async def test_supported_reference_requires_file_authority_and_real_image_inspection(monkeypatch):
    data, ref = reference()
    config = google_config()
    supplied = MediaGenerateInput(prompt="Synthetic", reference_image=ref)
    load = AsyncMock(return_value=files.not_found())
    monkeypatch.setattr(files, "load_verified", load)
    with pytest.raises(MediaOperationError) as refused:
        await _execution._reference(config, supplied)
    assert refused.value.code == "FILE_NOT_FOUND"
    stored = files.StoredFile(data=data, content_type="image/png", filename="sample.png")
    load.return_value = stored
    assert await _execution._reference(config, supplied) is stored
    load.assert_awaited_with(ref, max_bytes=_execution.MAX_REFERENCE_BYTES)
    monkeypatch.setattr(
        _execution,
        "inspect_media",
        AsyncMock(
            return_value=MediaInfo(
                kind="audio", media_type="audio/wav", byte_size=len(data), duration_seconds=1
            )
        ),
    )
    with pytest.raises(MediaOperationError, match="inspected image"):
        await _execution._reference(config, supplied)


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "no_close_method",
        "missing",
        "missing_midstream",
        "too_large",
        "digest",
        "size",
        "cancelled",
    ],
)
async def test_recovery_reads_one_bounded_identity_and_closes_its_stream(monkeypatch, case):
    row = operation()
    authorized = AsyncMock()
    monkeypatch.setattr(_output, "recheck", authorized)

    class Stream:
        def __init__(self):
            self.closed = False
            self.values = [b"synt", b"hetic"]
            if case == "missing_midstream":
                self.values = [b"synt", FileNotFoundError()]
            if case == "too_large":
                self.values = [b"x" * (row.reserved_bytes + 1)]
            if case == "digest":
                self.values = [b"a" * row.reserved_bytes]
            if case == "size":
                self.values = [b"x"]
            if case == "cancelled":
                self.values = [asyncio.CancelledError()]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.values:
                raise StopAsyncIteration
            value = self.values.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value

        async def aclose(self):
            self.closed = True

    stream = Stream()
    if case == "no_close_method":
        stream.aclose = None
    opened = AsyncMock(
        return_value=stream, side_effect=FileNotFoundError() if case == "missing" else None
    )
    monkeypatch.setattr(_output, "get_file_storage", lambda: SimpleNamespace(open_stream=opened))
    if case in {"too_large", "digest", "size", "cancelled"}:
        with pytest.raises(asyncio.CancelledError if case == "cancelled" else MediaOperationError):
            await _output.recover_bytes(row, image_config())
    else:
        assert await _output.recover_bytes(row, image_config()) == (
            b"synthetic" if case in {"valid", "no_close_method"} else None
        )
    assert stream.closed is (case not in {"missing", "no_close_method"})
    opened.assert_awaited_once_with(
        f"workflow-files/{row.organization_id}/{row.workflow_run_id}/{row.output_file_id}"
    )
    authorized.assert_awaited_once()


async def test_missing_journaled_image_bytes_never_authorize_a_replacement_submission(monkeypatch):
    row = operation()
    recover = AsyncMock(return_value=None)
    monkeypatch.setattr(_output, "recover_bytes", recover)
    with pytest.raises(MediaOperationError) as refused:
        await _execution._recover(row, image_config())
    assert refused.value.code == "MEDIA_OUTPUT_RECOVERY_REQUIRED"
    # An image response id is billing evidence only; it cannot collect the image.
    row.provider_receipt = {"kind": "response", "id": "resp_synthetic"}
    with pytest.raises(MediaOperationError, match="needs review"):
        await _execution._recover(row, image_config())
    row.media_kind, row.provider_receipt = "video", {"id": "existing-video"}
    assert await _execution._recover(row, image_config()) is None
    row.output_sha256 = None
    recover.reset_mock()
    assert await _execution._recover(row, image_config()) is None
    recover.assert_not_awaited()


@pytest.mark.parametrize(
    "database_available,started", [(False, False), (True, False), (True, True)]
)
async def test_interruption_never_claims_no_effect_when_its_journal_is_unavailable(
    monkeypatch, database_available, started
):
    journal = SimpleNamespace(
        id=uuid4(),
        interrupted=AsyncMock(
            side_effect=None if database_available else RuntimeError("private provider body")
        ),
        read=AsyncMock(
            return_value=SimpleNamespace(effect_started_at=object() if started else None)
        ),
    )
    result = await _execution._interrupted(journal, "SYNTHETIC_REFUSAL", "Controlled refusal")
    assert isinstance(result, Uncertain if not database_available or started else Failed)
    assert "private provider body" not in result.model_dump_json()


@pytest.mark.parametrize("journal_failure", [False, True])
async def test_cancellation_is_propagated_after_attempting_to_preserve_the_journal(
    monkeypatch, journal_failure
):
    row = operation()
    journal = SimpleNamespace(
        id=row.id,
        interrupted=AsyncMock(
            side_effect=RuntimeError("synthetic outage") if journal_failure else None
        ),
    )
    monkeypatch.setattr(_execution, "_reference", AsyncMock(return_value=None))
    monkeypatch.setattr(_execution, "admit", AsyncMock(return_value=row))
    monkeypatch.setattr(_execution, "MediaJournal", lambda _: journal)
    monkeypatch.setattr(_execution, "_recover", AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await _execution.generate(image_config(), MediaGenerateInput(prompt="Synthetic"))
    journal.interrupted.assert_awaited_once_with(reason="MEDIA_CANCELLED")


@pytest.mark.parametrize("variable,made", [(False, False), (False, True), (True, True)])
async def test_failed_video_download_books_only_known_generated_duration(
    monkeypatch, variable, made
):
    config = video_config(variable=variable)
    row = operation(config)
    journal = SimpleNamespace(start=AsyncMock(), receipt=AsyncMock(), cost=AsyncMock())

    @asynccontextmanager
    async def key(*_args):
        yield "synthetic-key", 30

    async def download(_provider, **kwargs):
        kwargs["reached"]("made" if made else "submitted")
        raise RuntimeError("Synthetic download refusal")

    monkeypatch.setattr(_execution, "effect_key", key)
    monkeypatch.setattr(_execution, "generate_video", download)
    monkeypatch.setattr(_execution.context, "current", lambda: object())
    with pytest.raises(RuntimeError, match="download refusal"):
        await _execution._video(row, journal, config, MediaGenerateInput(prompt="Synthetic"), None)
    journal.start.assert_awaited_once()
    if made and not variable:
        fact = journal.cost.await_args.args[0]
        assert fact.evidence.seconds == config.requested_seconds()
        assert fact.source == "catalog_estimate" and fact.held_usd == 0
    else:
        journal.cost.assert_not_awaited()


async def test_variable_video_without_observed_duration_keeps_its_maximum_unbooked(monkeypatch):
    config = video_config(variable=True)
    row = operation(config)
    journal = SimpleNamespace(start=AsyncMock(), receipt=AsyncMock(), cost=AsyncMock())

    @asynccontextmanager
    async def key(*_args):
        yield "synthetic-key", 30

    monkeypatch.setattr(_execution, "effect_key", key)
    monkeypatch.setattr(_execution.context, "current", lambda: object())
    provider = AsyncMock(return_value=Clip(data=b"synthetic", seconds=None))
    monkeypatch.setattr(_execution, "generate_video", provider)
    data, _kind = await _execution._video(
        row,
        journal,
        config,
        MediaGenerateInput(prompt="Synthetic"),
        files.StoredFile(data=png_bytes(), content_type="image/png", filename=None),
    )
    assert data == b"synthetic"
    assert provider.await_args.kwargs["first_frame"].mime_type == "image/png"
    journal.cost.assert_not_awaited()


async def test_image_reference_and_catalog_limit_reach_only_the_strict_shared_executor(monkeypatch):
    config = google_config()
    row = operation(config)
    journal = Mock()
    model = Mock()
    inspected = files.StoredFile(data=png_bytes(), content_type="image/png", filename="sample.png")

    @asynccontextmanager
    async def key(*_args):
        yield "synthetic-key", 30

    @asynccontextmanager
    async def opened(*_args):
        yield model

    generate = AsyncMock(return_value=BinaryImage(data=inspected.data, media_type="image/png"))
    monkeypatch.setattr(_execution, "effect_key", key)
    monkeypatch.setattr(_execution, "open_image_model", opened)
    monkeypatch.setattr(_execution, "DurableImageModel", lambda m, j, b: (m, j, b))
    monkeypatch.setattr(_execution, "generate_image", generate)
    assert await _execution._image(
        row, journal, config, MediaGenerateInput(prompt="Synthetic"), inspected
    ) == (inspected.data, "image/png")
    kwargs = generate.await_args.kwargs
    assert kwargs["reference_image"].data == inspected.data
    assert kwargs["model_settings"] == {"max_tokens": config.workflow_support().max_output_tokens}
    assert kwargs["instrument"] is False


async def test_stored_price_kind_and_removed_provider_cannot_authorize_execution(monkeypatch):
    image, video = image_config(), video_config()
    with pytest.raises(MediaOperationError, match="image price basis"):
        await _execution._image(
            operation(video), Mock(), image, MediaGenerateInput(prompt="Synthetic"), None
        )
    with pytest.raises(MediaOperationError, match="video price basis"):
        _execution._video_basis(operation(image))
    video_operation = operation(video)
    monkeypatch.setattr(_execution.video_models, "by_provider", lambda _: None)
    with pytest.raises(MediaOperationError, match="provider is unavailable"):
        await _execution._video(
            video_operation, Mock(), video, MediaGenerateInput(prompt="Synthetic"), None
        )


async def test_estimate_refuses_a_price_removed_since_config_validation(monkeypatch):
    from app.services import workflow_media_read

    config = video_config()
    monkeypatch.setattr(OrganizationSecretService, "workflow_media_secret", AsyncMock())
    monkeypatch.setattr(workflow_media_read, "video_support", lambda _: None)
    with pytest.raises(BadRequestError) as refused:
        await WorkflowMediaReadService(Mock()).estimate(
            Mock(), VideoMediaEstimateRequest(kind="video", config=config)
        )
    assert refused.value.code == "MEDIA_PRICE_UNAVAILABLE"


async def test_reference_capable_image_estimate_uses_its_own_token_caps_without_a_text_only_claim(
    monkeypatch,
):
    from app.schemas.workflow_media import ImageMediaEstimateRequest

    config = google_config()
    monkeypatch.setattr(OrganizationSecretService, "workflow_media_secret", AsyncMock())
    result = await WorkflowMediaReadService(Mock()).estimate(
        Mock(), ImageMediaEstimateRequest(kind="image", config=config)
    )
    codes = {item.code for item in result.assumptions}
    assert "image_token_ceiling" in codes
    assert "image_tool_ceiling" not in codes and "text_only" not in codes
    assert result.reservation_usd == config.reservation_usd()


@pytest.mark.parametrize("kind", ["image", "video"])
async def test_a_removed_provider_cannot_supply_a_fresh_dispatch_identity(monkeypatch, kind):
    config = image_config() if kind == "image" else video_config()
    catalog = _admission.image_models if kind == "image" else _admission.video_models
    monkeypatch.setattr(catalog, "by_provider", lambda _: None)
    with pytest.raises(MediaOperationError) as refused:
        _admission.provider_api(config)
    assert refused.value.code == "MEDIA_PROVIDER_UNAVAILABLE"


async def test_cancellation_during_reference_read_creates_no_operation_or_provider_effect(
    monkeypatch,
):
    admit = AsyncMock()
    monkeypatch.setattr(_execution, "admit", admit)
    monkeypatch.setattr(_execution, "_reference", AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await _execution.generate(google_config(), MediaGenerateInput(prompt="Synthetic"))
    admit.assert_not_awaited()


async def test_media_inspection_cannot_publish_an_audio_result_as_an_image(monkeypatch):
    inspected = AsyncMock(
        return_value=MediaInfo(
            kind="audio", media_type="audio/wav", byte_size=12, duration_seconds=1
        )
    )
    monkeypatch.setattr(_execution, "inspect_media", inspected)
    with pytest.raises(MediaOperationError) as refused:
        await _execution._inspect_output(image_config(), b"sample audio", "audio/wav")
    assert refused.value.code == "MEDIA_OUTPUT_KIND_REFUSED"
    inspected.assert_awaited_once()
