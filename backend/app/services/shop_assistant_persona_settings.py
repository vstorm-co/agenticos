"""CRUD for Shop assistant persona (D3 B59)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.schemas.shop_agent_background_job import ShopAgentBackgroundJobCreate
from app.services.shop_agent_background_job_service import ShopAgentBackgroundJobService
from app.db.models.shop_ai_settings import ShopAiSettings
from app.repositories import shop_ai_settings as settings_repo
from app.schemas.shop_assistant_persona import (
    ASSISTANT_TONES,
    ShopAssistantPersonaPatch,
    ShopAssistantPersonaRead,
)


class ShopAssistantPersonaService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_settings(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
    ) -> ShopAssistantPersonaRead:
        row = await settings_repo.get_or_create(
            self.db,
            minerp_tenant_id=minerp_tenant_id,
            organization_id=organization_id,
        )
        return self._to_read(row)

    async def patch_settings(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        data: ShopAssistantPersonaPatch,
    ) -> ShopAssistantPersonaRead:
        row = await settings_repo.get_or_create(
            self.db,
            minerp_tenant_id=minerp_tenant_id,
            organization_id=organization_id,
        )

        if "assistant_name" in data.model_fields_set:
            row.assistant_name = (data.assistant_name or "").strip() or None
        if "assistant_tone" in data.model_fields_set:
            tone = (data.assistant_tone or "").strip().lower() or None
            if tone and tone not in ASSISTANT_TONES:
                raise BadRequestError(
                    message="Invalid assistant tone",
                    details={"allowed": sorted(ASSISTANT_TONES)},
                )
            row.assistant_tone = tone
        if "assistant_custom_instructions" in data.model_fields_set:
            row.assistant_custom_instructions = (
                (data.assistant_custom_instructions or "").strip() or None
            )
        if data.merchant_morning_digest_enabled is not None:
            row.merchant_morning_digest_enabled = data.merchant_morning_digest_enabled
            await self._sync_morning_digest(
                organization_id=organization_id,
                minerp_tenant_id=minerp_tenant_id,
                enabled=row.merchant_morning_digest_enabled,
            )

        row.updated_at = datetime.now(UTC)
        await self.db.flush()
        await self.db.refresh(row)
        return self._to_read(row)

    async def _sync_morning_digest(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        enabled: bool,
    ) -> None:
        if not settings.SHOP_AGENT_BACKGROUND_JOB_ENABLED:
            return
        goal = (
            "Tóm tắt buổi sáng cho chủ shop: đơn hàng, chat chờ, sản phẩm bán chạy, "
            "và việc cần chú ý từ MCP đã kết nối."
        )
        svc = ShopAgentBackgroundJobService(self.db)
        if enabled:
            try:
                await svc.schedule(
                    ShopAgentBackgroundJobCreate(
                        job_type="digest",
                        goal=goal,
                        notify_channels=["in_app"],
                        digest_interval_hours=24,
                    ),
                    minerp_tenant_id=minerp_tenant_id,
                    organization_id=organization_id,
                )
            except BadRequestError:
                pass

    @staticmethod
    def _to_read(row: ShopAiSettings) -> ShopAssistantPersonaRead:
        return ShopAssistantPersonaRead(
            assistant_name=row.assistant_name,
            assistant_tone=row.assistant_tone,
            assistant_custom_instructions=row.assistant_custom_instructions,
            merchant_morning_digest_enabled=bool(row.merchant_morning_digest_enabled),
        )
