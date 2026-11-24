"""Validate an authorized run file and expose actual media metadata."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.permissions import AuthContext
from app.services.media_inspection import MediaInfo, MediaInspectionError, inspect_media
from app.services.workflow_execution import context
from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed, NodeResult


def _accepted_media() -> list[Literal["image", "audio", "video"]]:
    return ["image", "audio", "video"]


class AssetInputConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted_kinds: list[Literal["image", "audio", "video"]] = Field(
        default_factory=_accepted_media, min_length=1, max_length=3
    )
    max_bytes: int = Field(default=50_000_000, ge=1, le=300_000_000)
    max_pixels: int = Field(default=40_000_000, ge=1, le=40_000_000)
    max_seconds: float = Field(default=600, gt=0, le=3600, allow_inf_nan=False)
    required_input_name: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("accepted_kinds")
    @classmethod
    def distinct_kinds(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Name each accepted media kind only once")
        return value


class AssetInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file: FileRef


class AssetOutput(MediaInfo):
    file: FileRef


def available() -> bool:
    return settings.WORKFLOW_ASSET_INPUT_ENABLED


async def check_resources(
    _db: AsyncSession, _auth: AuthContext, _config: BaseModel
) -> list[tuple[str, str]]:
    return [] if available() else [("", "Asset inspection is disabled on this deployment")]


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not available():
        return files.failed("MEDIA_DISABLED", "Asset inspection is disabled on this deployment")
    if not isinstance(config, AssetInputConfig) or not isinstance(node_input, AssetInput):
        return files.failed("FILE_STEP_NOT_CONFIGURED", "Choose the media file to inspect")
    if config.required_input_name is not None:
        try:
            supplied = FileRef.model_validate(
                context.current().run_input.get(config.required_input_name)
            )
        except ValidationError:
            return files.failed("MEDIA_INPUT_REQUIRED", "The named run input must supply this file")
        if supplied != node_input.file:
            return files.failed("MEDIA_INPUT_REQUIRED", "The named run input must supply this file")
    stored = await files.load_verified(node_input.file, max_bytes=config.max_bytes)
    if isinstance(stored, Failed):
        return stored
    try:
        metadata = await inspect_media(
            stored.data,
            expected_type=stored.content_type,
            max_bytes=config.max_bytes,
            max_pixels=min(config.max_pixels, settings.CHAT_IMAGE_MAX_PIXELS),
            max_seconds=config.max_seconds,
        )
    except MediaInspectionError as exc:
        return files.failed(exc.code, str(exc))
    except TimeoutError:
        return files.failed(
            "MEDIA_INSPECTION_TIMEOUT", "The media inspection exceeded its deadline"
        )
    if metadata.kind not in config.accepted_kinds:
        return files.failed("MEDIA_KIND_REFUSED", "This step does not accept that media kind")
    return Completed[AssetOutput](output=AssetOutput(file=node_input.file, **metadata.model_dump()))
