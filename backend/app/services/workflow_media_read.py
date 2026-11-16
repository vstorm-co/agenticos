"""Media pricing without an effect, and safe projections of the durable journal."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.db.models.workflow_media_operation import WorkflowMediaOperation
from app.repositories import workflow_media_operation as media_repo
from app.schemas.workflow_media import (
    ImageTokenCeilingAssumption,
    ImageToolCeilingAssumption,
    SimpleMediaEstimateAssumption,
    VideoDurationRateAssumption,
    WorkflowMediaEstimateAssumption,
    WorkflowMediaEstimateRead,
    WorkflowMediaEstimateRequest,
    WorkflowMediaOperationRead,
    WorkflowMediaRetryEffect,
)
from app.services.organization_secret import OrganizationSecretService
from app.services.workflow_media_catalog import image_options, video_support
from app.workflows.nodes._media_config import ImageGenerateConfig


class WorkflowMediaReadService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def for_nodes(
        self, *, organization_id: UUID, workflow_run_id: UUID, node_run_ids: list[UUID]
    ) -> dict[UUID, WorkflowMediaOperationRead]:
        """Called only after the existing run reader has authorized its page."""
        rows = await media_repo.current_for_nodes(
            self.db,
            organization_id=organization_id,
            workflow_run_id=workflow_run_id,
            node_run_ids=node_run_ids,
        )
        return {
            node_id: WorkflowMediaOperationRead.model_validate(
                {
                    "operation_id": operation.id,
                    "phase": operation.phase,
                    "held_usd": operation.held_usd,
                    "incurred_usd": operation.incurred_usd,
                    "booked_usd": operation.booked_usd,
                    "cost_source": operation.cost_source,
                    "accounting_complete": operation.accounting_complete,
                    "node_unresolved_usd": total,
                    "has_receipt": operation.provider_receipt is not None,
                    "retry_effect": retry_effect(operation),
                }
            )
            for node_id, (operation, total) in rows.items()
        }

    async def estimate(
        self, ctx: AuthContext, data: WorkflowMediaEstimateRequest
    ) -> WorkflowMediaEstimateRead:
        """Resolve current metadata and catalog prices without unwrapping a key."""
        config = data.config
        await OrganizationSecretService(self.db).workflow_media_secret(
            ctx, config.secret_id, provider=config.provider
        )
        reservation = config.reservation_usd()
        cap = Decimal(str(config.max_cost_usd)) if config.max_cost_usd is not None else None
        assumptions: list[WorkflowMediaEstimateAssumption] = [
            SimpleMediaEstimateAssumption(code="conservative_reservation"),
            SimpleMediaEstimateAssumption(code="single_submission"),
            SimpleMediaEstimateAssumption(code="dispatch_limits_rechecked"),
            SimpleMediaEstimateAssumption(code="unresolved_hold_retained"),
        ]
        if isinstance(config, ImageGenerateConfig):
            support = config.workflow_support()
            pricing_as_of = support.pricing_as_of
            assumptions.append(
                ImageTokenCeilingAssumption(
                    max_input_tokens=support.max_input_tokens,
                    max_output_tokens=support.max_output_tokens,
                )
            )
            if support.output_prices:
                options = image_options(config.provider, config.model, config)
                chosen = next(
                    item
                    for item in support.output_prices
                    if item.size == options.size and item.quality == options.quality
                )
                assumptions.append(
                    ImageToolCeilingAssumption(
                        prompt_max_characters=support.tool_prompt_max_characters,
                        quality=chosen.quality,
                        size=chosen.size,
                        output_estimate_usd=chosen.output_estimate_usd,
                        output_ceiling_usd=chosen.output_ceiling_usd,
                    )
                )
            if not support.reference_image:
                assumptions.append(SimpleMediaEstimateAssumption(code="text_only"))
        else:
            request = config.request_config()
            model = request.chosen_model()
            support = video_support(model)
            # The node schema already requires a priced model. Re-evaluate the
            # dated catalog here so estimate and admission use the same contract.
            if support is None:
                raise BadRequestError(
                    code="MEDIA_PRICE_UNAVAILABLE",
                    message="This video model has no current catalog price",
                )
            pricing_as_of = support.pricing_as_of
            duration = config.requested_seconds() or model.max_seconds
            assumptions.append(
                VideoDurationRateAssumption(
                    seconds=duration,
                    resolution=request.resolved_resolution(),
                    usd_per_second=support.usd_per_second[request.resolved_resolution()],
                    uses_model_maximum=config.requested_seconds() is None,
                    sound_on_ceiling=model.audio == "optional",
                )
            )
        return WorkflowMediaEstimateRead(
            kind=data.kind,
            provider=config.provider,
            model=config.model,
            reservation_usd=reservation,
            reserved_bytes=config.max_output_bytes,
            pricing_as_of=pricing_as_of,
            configured_max_cost_usd=cap,
            sufficient_max_cost_usd=cap is None or cap >= reservation,
            deficit_usd=max(reservation - cap, Decimal(0)) if cap is not None else Decimal(0),
            assumptions=assumptions,
        )


def retry_effect(operation: WorkflowMediaOperation) -> WorkflowMediaRetryEffect:
    if operation.phase == "stored":
        return "recover_output"
    if operation.phase in {"failed", "cancelled"}:
        return "new_billable_submission"
    if operation.output_sha256 is not None:
        return "recover_output"
    if operation.provider_receipt is not None:
        return "collect_existing"
    if operation.phase in {"submitting", "unknown"}:
        return "reconciliation_required"
    return "none"
