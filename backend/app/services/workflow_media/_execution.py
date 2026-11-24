"""One bounded submission or collection, followed by an authorized atomic publication."""

import asyncio
import hashlib
import logging

from pydantic_ai.messages import BinaryContent
from pydantic_ai.native_tools import ImageGenerationTool
from pydantic_ai.settings import ModelSettings

from app.core.config import settings
from app.core.exceptions import AppException
from app.db.models.workflow_media_operation import WorkflowMediaOperation
from app.services import image_models, video_models
from app.services.image_generation import generate_image, open_image_model
from app.services.media_inspection import MediaInfo, MediaInspectionError, inspect_media
from app.services.video_generation import FirstFrame, VideoReceipt, generate_video
from app.services.workflow_execution import context
from app.services.workflow_media import _output
from app.services.workflow_media._admission import MediaConfig, admit, effect_key
from app.services.workflow_media._errors import MediaOperationError
from app.services.workflow_media._image_model import DurableImageModel
from app.services.workflow_media._journal import MediaJournal
from app.services.workflow_media._pricing import (
    ImagePriceBasis,
    VideoPriceBasis,
    price_basis_adapter,
    video_cost,
)
from app.services.workflow_media_catalog import reference_supported
from app.workflows import files
from app.workflows.contracts.results import Completed, Failed, NodeResult, Uncertain, WorkflowError
from app.workflows.nodes._media_config import (
    ImageGenerateConfig,
    MediaGenerateInput,
    VideoGenerateConfig,
)

logger = logging.getLogger(__name__)
MAX_REFERENCE_BYTES = 20_000_000


async def _reference(config: MediaConfig, supplied: MediaGenerateInput) -> files.StoredFile | None:
    if supplied.reference_image is None:
        return None
    kind = "image.generate" if isinstance(config, ImageGenerateConfig) else "video.generate"
    if not reference_supported(kind, config.provider, config.model):
        raise MediaOperationError(
            "MEDIA_REFERENCE_REFUSED", "This model does not accept a workflow reference image"
        )
    stored = await files.load_verified(supplied.reference_image, max_bytes=MAX_REFERENCE_BYTES)
    if isinstance(stored, Failed):
        raise MediaOperationError(stored.error.code, stored.error.message)
    metadata = await inspect_media(
        stored.data,
        expected_type=stored.content_type,
        max_bytes=MAX_REFERENCE_BYTES,
        max_pixels=settings.CHAT_IMAGE_MAX_PIXELS,
        max_seconds=1,
    )
    if metadata.kind != "image":
        raise MediaOperationError(
            "MEDIA_REFERENCE_REFUSED", "The reference must be an inspected image"
        )
    return stored


async def _image(
    operation: WorkflowMediaOperation,
    journal: MediaJournal,
    config: ImageGenerateConfig,
    supplied: MediaGenerateInput,
    reference: files.StoredFile | None,
) -> tuple[bytes, str]:
    basis = price_basis_adapter.validate_python(operation.pricing_snapshot)
    if not isinstance(basis, ImagePriceBasis):
        raise MediaOperationError(
            "MEDIA_PRICE_MISMATCH", "The image price basis cannot be recovered"
        )
    async with (
        effect_key(operation, config) as (key, seconds),
        asyncio.timeout(seconds),
        open_image_model(
            image_models.resolved_model_id(config.provider, config.model), key
        ) as model,
    ):
        generated = await generate_image(
            DurableImageModel(model, journal, basis),
            prompt=supplied.prompt,
            tool=ImageGenerationTool(**config.request_config().to_tool_kwargs()),
            reference_image=(
                BinaryContent(data=reference.data, media_type=reference.content_type)
                if reference is not None
                else None
            ),
            model_settings=ModelSettings(max_tokens=basis.catalog.max_output_tokens),
            instrument=False,
        )
    return generated.data, generated.media_type


def _video_basis(operation: WorkflowMediaOperation) -> VideoPriceBasis:
    basis = price_basis_adapter.validate_python(operation.pricing_snapshot)
    if not isinstance(basis, VideoPriceBasis):
        raise MediaOperationError(
            "MEDIA_PRICE_MISMATCH", "The video price basis cannot be recovered"
        )
    return basis


async def _video(
    operation: WorkflowMediaOperation,
    journal: MediaJournal,
    config: VideoGenerateConfig,
    supplied: MediaGenerateInput,
    reference: files.StoredFile | None,
) -> tuple[bytes, str]:
    basis = _video_basis(operation)
    provider = video_models.by_provider(config.provider)
    if provider is None:
        raise MediaOperationError(
            "MEDIA_PROVIDER_UNAVAILABLE", "This video provider is unavailable"
        )
    receipt = (
        VideoReceipt.model_validate(operation.provider_receipt)
        if operation.provider_receipt
        else None
    )
    request = config.request_config()
    made = False

    def reached(stage: str) -> None:
        nonlocal made
        made = made or stage == "made"

    try:
        async with effect_key(operation, config) as (key, seconds), asyncio.timeout(seconds):
            if receipt is None:
                await journal.start(context.current())
            clip = await generate_video(
                provider,
                model=config.model,
                prompt=supplied.prompt,
                resolution=request.resolved_resolution(),
                aspect_ratio=request.aspect_ratio or request.chosen_model().aspect_ratios[0],
                api_key=key,
                timeout_seconds=seconds,
                duration=request.seconds,
                audio=request.audio,
                first_frame=(
                    FirstFrame(data=reference.data, mime_type=reference.content_type)
                    if reference
                    else None
                ),
                receipt=receipt,
                on_receipt=journal.receipt,
                reached=reached,
                protected_downloads=True,
            )
    except BaseException:
        # A completed fixed-duration job is incurred even when its download is
        # refused or interrupted. An unused maximum for variable video is not.
        if made and basis.requested_seconds is not None:
            await journal.cost(video_cost(basis, seconds=basis.requested_seconds))
        raise
    seconds_made = clip.seconds if clip.seconds is not None else basis.requested_seconds
    if seconds_made is not None:
        await journal.cost(video_cost(basis, seconds=seconds_made))
    return clip.data, files.sniff(clip.data)


async def _inspect_output(config: MediaConfig, data: bytes, media_type: str) -> MediaInfo:
    maximum_seconds = (
        1
        if isinstance(config, ImageGenerateConfig)
        else config.request_config().chosen_model().max_seconds
    )
    metadata = await inspect_media(
        data,
        expected_type=media_type,
        max_bytes=config.max_output_bytes,
        max_pixels=min(config.max_output_pixels, settings.CHAT_IMAGE_MAX_PIXELS),
        max_seconds=maximum_seconds,
    )
    expected = "image" if isinstance(config, ImageGenerateConfig) else "video"
    if metadata.kind != expected:
        raise MediaOperationError(
            "MEDIA_OUTPUT_KIND_REFUSED", "The provider returned a different media kind"
        )
    return metadata


def _refused(code: str, message: str) -> Failed:
    return Failed(
        error=WorkflowError(code=code, message=message, retryable=False, bypassable=False)
    )


async def _interrupted(journal: MediaJournal | None, code: str, message: str) -> NodeResult:
    if journal is None:
        return _refused(code, message)
    try:
        await journal.interrupted(reason=code)
        row = await journal.read()
    except Exception:
        # The committed submitting record remains the evidence if the database
        # becomes unavailable. Never turn a journal outage into another POST.
        logger.warning(
            "workflow_media_reconciliation_pending",
            extra={"operation_id": str(journal.id), "code": code},
        )
        return Uncertain(detail="The media operation must be reconciled before another submission")
    if row.effect_started_at is None:
        return _refused(code, message)
    return Uncertain(
        detail="The media operation retained its receipt and unresolved costs; check its status before retrying"
    )


async def _recover(operation: WorkflowMediaOperation, config: MediaConfig) -> bytes | None:
    if operation.output_sha256 is None:
        return None
    data = await _output.recover_bytes(operation, config)
    if data is None and (operation.media_kind == "image" or operation.provider_receipt is None):
        raise MediaOperationError(
            "MEDIA_OUTPUT_RECOVERY_REQUIRED",
            "The journaled image output is unavailable; a new submission needs review",
        )
    return data


async def generate(config: MediaConfig, supplied: MediaGenerateInput) -> NodeResult:
    journal: MediaJournal | None = None
    try:
        reference = await _reference(config, supplied)
        operation = await admit(
            config,
            supplied,
            reference_sha256=hashlib.sha256(reference.data).hexdigest() if reference else None,
        )
        journal = MediaJournal(operation)
        data = await _recover(operation, config)
        if data is None:
            if isinstance(config, ImageGenerateConfig):
                data, media_type = await _image(operation, journal, config, supplied, reference)
            else:
                data, media_type = await _video(operation, journal, config, supplied, reference)
            try:
                metadata = await _inspect_output(config, data, media_type)
            except (MediaInspectionError, MediaOperationError) as exc:
                await journal.reject_output(reason=exc.code)
                return _refused(exc.code, str(exc))
            if isinstance(config, VideoGenerateConfig) and metadata.duration_seconds is not None:
                await journal.cost(
                    video_cost(_video_basis(operation), seconds=metadata.duration_seconds)
                )
            operation = await journal.output(data, metadata)
        output = await _output.persist(operation, config, data)
        return Completed(output=output)
    except asyncio.CancelledError:
        if journal is not None:
            try:
                await asyncio.shield(journal.interrupted(reason="MEDIA_CANCELLED"))
            except Exception:
                logger.warning(
                    "workflow_media_cancellation_pending", extra={"operation_id": str(journal.id)}
                )
        raise
    except (AppException, MediaInspectionError) as exc:
        return await _interrupted(journal, exc.code, str(exc))
    except Exception:
        # Raw provider exceptions may contain URLs, prompts and credentials.
        return await _interrupted(
            journal,
            "MEDIA_PROVIDER_INTERRUPTED",
            "The media provider did not return a usable result",
        )
