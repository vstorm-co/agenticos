"""Shop FAQ curation settings — default suggestion KB + auto-draft threshold."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.repositories import knowledge_base_repo, shop_ai_settings as settings_repo
from app.schemas.shop_faq_settings import ShopFaqSettingsPatch, ShopFaqSettingsRead
from app.services.shop_faq_suggestion_utils import is_faq_kb


class ShopFaqSettingsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_settings(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
    ) -> ShopFaqSettingsRead:
        row = await settings_repo.get_or_create(
            self.db,
            minerp_tenant_id=minerp_tenant_id,
            organization_id=organization_id,
        )
        kb_id = row.default_faq_suggestion_kb_id
        if kb_id is None:
            for candidate in await knowledge_base_repo.list_org_scoped(self.db, organization_id):
                if is_faq_kb(candidate):
                    row = await settings_repo.set_default_faq_suggestion_kb_id(
                        self.db,
                        minerp_tenant_id,
                        organization_id=organization_id,
                        kb_id=candidate.id,
                    )
                    kb_id = row.default_faq_suggestion_kb_id
                    break
        kb_name: str | None = None
        if kb_id is not None:
            kb = await knowledge_base_repo.get_by_id(self.db, kb_id)
            if kb is not None and kb.organization_id == organization_id and is_faq_kb(kb):
                kb_name = kb.name
            else:
                kb_id = None
        return ShopFaqSettingsRead(
            default_faq_suggestion_kb_id=kb_id,
            default_faq_suggestion_kb_name=kb_name,
            auto_draft_faq_min_occurrences=row.auto_draft_faq_min_occurrences,
        )

    async def patch_settings(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        data: ShopFaqSettingsPatch,
    ) -> ShopFaqSettingsRead:
        if "default_faq_suggestion_kb_id" in data.model_fields_set:
            kb_id = data.default_faq_suggestion_kb_id
            if kb_id is not None:
                kb = await knowledge_base_repo.get_by_id(self.db, kb_id)
                if kb is None or kb.organization_id != organization_id:
                    raise NotFoundError(
                        message="Knowledge base not found for organization",
                        details={"kb_id": str(kb_id), "organization_id": str(organization_id)},
                    )
                if not is_faq_kb(kb):
                    raise BadRequestError(
                        message="Cannot use catalog knowledge base as default FAQ suggestion KB",
                        details={"kb_id": str(kb_id)},
                    )
            await settings_repo.set_default_faq_suggestion_kb_id(
                self.db,
                minerp_tenant_id,
                organization_id=organization_id,
                kb_id=kb_id,
            )
        if data.auto_draft_faq_min_occurrences is not None:
            await settings_repo.set_auto_draft_faq_min_occurrences(
                self.db,
                minerp_tenant_id,
                organization_id=organization_id,
                min_occurrences=data.auto_draft_faq_min_occurrences,
            )
        return await self.get_settings(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
        )
