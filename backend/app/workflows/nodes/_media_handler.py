"""Shared metadata-only publication checks and controlled generation entry."""

from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.services.organization_secret import OrganizationSecretService
from app.services.workflow_media._execution import generate
from app.workflows.contracts.results import Failed, NodeResult, WorkflowError
from app.workflows.nodes._media_config import (
    ImageGenerateConfig,
    MediaGenerateInput,
    VideoGenerateConfig,
)


def available(kind: str) -> bool:
    return (
        settings.WORKFLOW_IMAGE_GENERATION_ENABLED
        if kind == "image"
        else settings.WORKFLOW_VIDEO_GENERATION_ENABLED
    )


async def check_resources(
    db: AsyncSession, auth: AuthContext, config: BaseModel, *, kind: str
) -> list[tuple[str, str]]:
    if not available(kind):
        return [("", "Media generation is disabled on this deployment")]
    expected = ImageGenerateConfig if kind == "image" else VideoGenerateConfig
    if not isinstance(config, expected):
        return [("", "Choose a supported media provider and model")]
    try:
        await OrganizationSecretService(db).workflow_media_secret(
            auth, config.secret_id, provider=config.provider
        )
    except AppException:
        return [("secret_id", "Choose an organization provider API key you may use")]
    if (
        config.max_cost_usd is not None
        and Decimal(str(config.max_cost_usd)) < config.reservation_usd()
    ):
        return [("max_cost_usd", "This cap is below the media request's conservative reservation")]
    return []


async def handle(config: BaseModel | None, supplied: BaseModel | None, *, kind: str) -> NodeResult:
    if not available(kind):
        return Failed(
            error=WorkflowError(
                code="MEDIA_DISABLED",
                message="Media generation is disabled on this deployment",
                bypassable=False,
            )
        )
    expected = ImageGenerateConfig if kind == "image" else VideoGenerateConfig
    if not isinstance(config, expected) or not isinstance(supplied, MediaGenerateInput):
        return Failed(
            error=WorkflowError(
                code="MEDIA_STEP_NOT_CONFIGURED",
                message="Choose a media provider, model, key and prompt",
            )
        )
    return await generate(config, supplied)
