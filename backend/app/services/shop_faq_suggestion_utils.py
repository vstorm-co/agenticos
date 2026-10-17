"""FAQ suggestion text normalization (D3 B56)."""

from __future__ import annotations

import hashlib
import re
import unicodedata

from app.db.models.knowledge_base import KnowledgeBase

_CATALOG_KB_NAME_MARKERS = frozenset({"shop catalog", "minerp shop catalog", "catalog sync"})


def is_faq_kb(kb: KnowledgeBase) -> bool:
    name = (kb.name or "").strip().lower()
    return name not in _CATALOG_KB_NAME_MARKERS and "catalog sync" not in name


def normalize_question(text: str) -> str:
    s = (text or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[?.!?,;:]+$", "", s).strip()
    return s


def question_fingerprint(text: str) -> str:
    norm = normalize_question(text)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]
