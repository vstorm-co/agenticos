"""Optional client actions returned with Shop widget chat replies."""

from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class ShopWidgetAddToCartAction(BaseSchema):
    type: Literal["add_to_cart"] = "add_to_cart"
    item_id: UUID
    quantity: int = Field(default=1, ge=1, le=99)


class ShopWidgetUpdateCartLineAction(BaseSchema):
    type: Literal["update_cart_line"] = "update_cart_line"
    item_id: UUID
    quantity: int = Field(default=1, ge=1, le=99)


class ShopWidgetRemoveCartLineAction(BaseSchema):
    type: Literal["remove_cart_line"] = "remove_cart_line"
    item_id: UUID


class ShopWidgetApplyVoucherAction(BaseSchema):
    type: Literal["apply_voucher"] = "apply_voucher"
    offer_code: str = Field(..., min_length=2, max_length=64)


class ShopWidgetOpenCartAction(BaseSchema):
    type: Literal["open_cart"] = "open_cart"


class ShopWidgetNavigateAction(BaseSchema):
    type: Literal["navigate"] = "navigate"
    href: str = Field(..., min_length=1, max_length=2048)


ShopWidgetAction = Annotated[
    Union[
        ShopWidgetAddToCartAction,
        ShopWidgetUpdateCartLineAction,
        ShopWidgetRemoveCartLineAction,
        ShopWidgetApplyVoucherAction,
        ShopWidgetOpenCartAction,
        ShopWidgetNavigateAction,
    ],
    Field(discriminator="type"),
]
