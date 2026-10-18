"""Render catalog items as plain text for RAG ingestion (Shop A P4-T3)."""

from __future__ import annotations

import hashlib
import re
from html import unescape
from typing import Any

_MAX_CHARS = 4000

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    cleaned = unescape(text)
    cleaned = _TAG_RE.sub(" ", cleaned)
    return _WS_RE.sub(" ", cleaned).strip()


def _format_price(item: dict[str, Any]) -> str | None:
    sale = item.get("sale_price")
    regular = item.get("regular_price")
    amount = sale if sale is not None else regular
    if amount is None:
        return None
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return None
    currency = item.get("currency") or "VND"
    return f"{value:,.0f} {currency} (snapshot — may be outdated)"


def _format_attributes(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("brand_name", "type_code", "style_code", "color_code", "size_code"):
        val = item.get(key)
        if val:
            parts.append(f"{key}={val}")
    return ", ".join(parts)


def render_catalog_item_text(item: dict[str, Any]) -> str:
    name = item.get("name") or "Product"
    sku = item.get("sku") or item.get("style_code") or str(item.get("id") or "")
    lines = [
        f"Product: {name}",
        f"SKU: {sku}",
    ]
    category = item.get("category_path")
    if category:
        lines.append(f"Category: {category}")
    price_label = _format_price(item)
    if price_label:
        lines.append(f"Price: {price_label}")
    description = strip_html(item.get("description"))
    if description:
        lines.append(f"Description: {description}")
    attrs = _format_attributes(item)
    if attrs:
        lines.append(f"Attributes: {attrs}")
    slug = item.get("cms_slug")
    if slug:
        lines.append(f"URL: /products/{slug}")
    in_stock = item.get("in_stock")
    if in_stock is not None:
        lines.append(f"In stock (snapshot): {'yes' if in_stock else 'no'}")
    text = "\n".join(lines)
    if len(text) > _MAX_CHARS:
        text = text[: _MAX_CHARS - 3] + "..."
    return text


def catalog_item_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
