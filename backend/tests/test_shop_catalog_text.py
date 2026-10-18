"""Catalog text rendering."""

from app.services.shop_catalog_text import catalog_item_hash, render_catalog_item_text


def test_render_catalog_item_text_stable_hash() -> None:
    item = {
        "id": "abc",
        "name": "Áo thun",
        "sku": "AT-01",
        "regular_price": 199000,
        "currency": "VND",
        "description": "<p>Mềm mại</p>",
        "lifecycle_status_code": "ACTIVE",
    }
    text = render_catalog_item_text(item)
    assert "Áo thun" in text
    assert catalog_item_hash(text) == catalog_item_hash(render_catalog_item_text(item))
