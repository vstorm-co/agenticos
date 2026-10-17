"""Heuristics for widget chatbot quality signals (D3 B61)."""

from __future__ import annotations

import json
import re
import unicodedata

_RAW_TOOL_JSON_RE = re.compile(r'^\s*\{\s*"name"\s*:', re.DOTALL)

_NO_RESULT_PHRASES = (
    "không tìm thấy sản phẩm",
    "khong tim thay san pham",
    "chưa có thông tin",
    "chua co thong tin",
)

_WEAK_REPLY_PHRASES = (
    "xin lỗi",
    "xin loi",
    "sorry",
    "không rõ",
    "khong ro",
    "không chắc",
    "khong chac",
    "liên hệ shop",
    "lien he shop",
    "gọi hotline",
    "goi hotline",
    "thử lại sau",
    "thu lai sau",
    "vui lòng thử lại",
    "vui long thu lai",
    "mình chưa hiểu",
    "minh chua hieu",
)


def _ascii_fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def looks_like_raw_tool_call(reply: str) -> bool:
    text = (reply or "").strip()
    if not text:
        return False
    if _RAW_TOOL_JSON_RE.match(text):
        return True
    if text.startswith("{") and text.endswith("}"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return False
        return isinstance(data, dict) and "name" in data and "arguments" in data
    return False


def looks_like_failed_product_search(reply: str) -> bool:
    lowered = (reply or "").lower()
    folded = _ascii_fold(lowered)
    return any(phrase in lowered or phrase in folded for phrase in _NO_RESULT_PHRASES)


def looks_like_weak_assistant_reply(reply: str) -> bool:
    if looks_like_raw_tool_call(reply):
        return True
    if looks_like_failed_product_search(reply):
        return True
    lowered = (reply or "").lower().strip()
    folded = _ascii_fold(lowered)
    return any(phrase in lowered or phrase in folded for phrase in _WEAK_REPLY_PHRASES)
