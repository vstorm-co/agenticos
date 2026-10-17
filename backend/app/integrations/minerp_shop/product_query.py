"""Normalize Vietnamese shop product search queries (aligned with multi-agent)."""

from __future__ import annotations

import re
import unicodedata

_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)

_STOPWORDS = frozenset(
    {
        "a",
        "ah",
        "ao",
        "ban",
        "bán",
        "bao",
        "cho",
        "co",
        "có",
        "cua",
        "của",
        "cửa",
        "dang",
        "đang",
        "em",
        "gi",
        "gia",
        "giá",
        "hang",
        "hàng",
        "hoi",
        "hỏi",
        "k",
        "khong",
        "không",
        "ko",
        "minh",
        "mình",
        "nhieu",
        "nhiêu",
        "oi",
        "ơi",
        "shop",
        "tim",
        "tìm",
        "toi",
        "tôi",
        "ve",
        "về",
        "vnd",
        "xin",
    }
)

_ASCII_PHRASES: tuple[tuple[str, str], ...] = (
    ("banh mi", "bánh mì"),
    ("ca phe", "cà phê"),
    ("caphe", "cà phê"),
    ("nuoc suoi", "nước suối"),
    ("nuoc khoang", "nước khoáng"),
    ("thit nuong", "thịt nướng"),
)


def _ascii_fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t and t not in _STOPWORDS and len(t) >= 2]


def catalog_search_candidates(user_text: str, *, max_candidates: int = 8) -> list[str]:
    raw = (user_text or "").strip()
    if not raw:
        return []

    lowered = raw.lower()
    folded = _ascii_fold(lowered)
    candidates: list[str] = []

    def add(value: str) -> None:
        value = value.strip()
        if value and value not in candidates:
            candidates.append(value)

    add(raw)
    add(lowered)
    if folded != lowered:
        add(folded)

    for ascii_phrase, vn_phrase in _ASCII_PHRASES:
        if ascii_phrase in lowered or ascii_phrase in folded:
            add(vn_phrase)

    tokens = _tokens(lowered) or _tokens(folded)
    if tokens:
        add(" ".join(tokens))
        if len(tokens) >= 2:
            add(" ".join(tokens[:2]))
        for token in tokens:
            add(token)

    return candidates[:max_candidates]
