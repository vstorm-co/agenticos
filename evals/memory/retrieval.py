"""A raw-session baseline, a common evidence budget and provenance metrics."""

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from dataset import Case, Query
from pydantic import BaseModel


class Evidence(BaseModel):
    source_id: str | None
    text: str
    date: datetime | None = None


@dataclass(frozen=True)
class Retrieved:
    evidence: list[Evidence]
    ingest_ms: float
    recall_ms: float
    cost_usd: float | None


def terms(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


def bm25(query: Query, top_k: int) -> list[Evidence]:
    """BM25 over full role-labeled sessions, with stable chronology as the tie break."""
    tokens = set(terms(query.question))
    documents = [Counter(terms(session.text)) for session in query.sessions]
    lengths = [doc.total() for doc in documents]
    average = sum(lengths) / max(1, len(documents)) or 1
    frequency = Counter(term for doc in documents for term in tokens.intersection(doc))
    weights = {
        term: math.log1p((len(documents) - count + 0.5) / (count + 0.5))
        for term, count in frequency.items()
    }
    scores = []
    for doc, length in zip(documents, lengths, strict=True):
        norm = 1.2 * (0.25 + 0.75 * length / average)
        scores.append(
            sum(
                weights[term] * count * 2.2 / (count + norm)
                for term, count in doc.items()
                if term in weights
            )
        )
    ranked = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
    return [
        Evidence(
            source_id=query.sessions[index].id,
            text=query.sessions[index].text,
            date=query.sessions[index].date,
        )
        for index in ranked[:top_k]
        if scores[index] > 0
    ]


def fit_evidence(rows: Iterable[Evidence], top_k: int, budget: int) -> list[Evidence]:
    """Cap ranked evidence units and their total text without inventing provenance."""
    result = []
    for row in rows:
        if len(result) == top_k or budget <= 0:
            break
        if not row.text.strip():
            continue
        text = row.text[:budget]
        result.append(row.model_copy(update={"text": text}))
        budget -= len(text)
    return result


def score(case: Case, rows: list[Evidence]) -> dict[str, float | None]:
    valid = {session.id for session in case.query.sessions}
    seen = {row.source_id for row in rows if row.source_id in valid}
    reciprocal = next(
        (1 / rank for rank, row in enumerate(rows, 1) if row.source_id in case.gold),
        0.0,
    )
    return {
        "hit": float(bool(seen & case.gold)) if case.gold else None,
        "recall": len(seen & case.gold) / len(case.gold) if case.gold else None,
        "all_evidence": float(case.gold <= seen) if case.gold else None,
        "mrr": reciprocal if case.gold else None,
        "empty": float(not rows),
        "provenance": sum(row.source_id in valid for row in rows) / len(rows) if rows else None,
    }
