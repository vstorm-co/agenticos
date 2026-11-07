"""Google Slides native integration."""

from typing import ClassVar

from pydantic import ConfigDict

from app.agents.capabilities._registry import CapabilityBuildContext, CapabilityToolInfo, register
from app.agents.capabilities.google_slides._capability import NativeIntegration
from app.agents.capabilities.google_slides._toolset import build_toolset
from app.services.integrations import PRODUCTS, AccountSelection

_PRODUCT = PRODUCTS["google_slides"]


class ProductConfig(AccountSelection):
    model_config = ConfigDict(json_schema_extra={"x-integration-provider": _PRODUCT.provider})
    _product_id: ClassVar[str | None] = "google_slides"


@register(
    id=_PRODUCT.id,
    name=_PRODUCT.name,
    category="integrations",
    description="Use " + _PRODUCT.name + " through a connected account, with approval for writes.",
    config_schema=ProductConfig,
    tools=tuple(
        CapabilityToolInfo(
            id=f"{_PRODUCT.id}_{operation.id}",
            description=operation.description,
            side_effecting=operation.side_effecting,
            always_requires_approval=operation.side_effecting,
        )
        for operation in _PRODUCT.operations
    ),
)
def _build(ctx: CapabilityBuildContext) -> NativeIntegration:
    config = ProductConfig.model_validate(ctx.config)
    return NativeIntegration(toolset=build_toolset(_PRODUCT.id, config))
