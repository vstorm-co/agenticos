"""Portable BM25 ranking over the tools already authorized for this run."""

import json
import math
import re
from collections import Counter
from collections.abc import Sequence

from pydantic_ai.tools import RunContext, ToolDefinition


def _terms(text: str) -> list[str]:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return re.findall(r"[^\W_]+", separated.casefold())


def rank_tools(
    ctx: RunContext[object], queries: Sequence[str], tools: Sequence[ToolDefinition]
) -> Sequence[str]:
    """Rank matching identifiers, descriptions and argument schemas without model IO."""
    if not tools:
        return []
    query = set(_terms(" ".join(queries)))
    if not query:
        return []
    documents = [
        Counter(
            _terms(
                f"{tool.name} {tool.name} {tool.name} {tool.description or ''} "
                f"{json.dumps(list(tool.parameters_json_schema.get('properties', {})), ensure_ascii=False)}"
            )
        )
        for tool in tools
    ]
    frequency = Counter(term for document in documents for term in document)
    average = sum(sum(document.values()) for document in documents) / len(documents)
    scores: list[tuple[float, str]] = []
    for tool, document in zip(tools, documents, strict=True):
        length = sum(document.values())
        score = 0.0
        for term in query:
            count = document[term]
            if count:
                rarity = math.log(
                    1 + (len(tools) - frequency[term] + 0.5) / (frequency[term] + 0.5)
                )
                score += rarity * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * length / average))
        identifiers = _terms(tool.name)
        for raw in queries:
            terms = _terms(raw)
            if terms and (terms == identifiers or terms == identifiers[1:]):
                score += 100.0
        if score > 0:
            scores.append((score, tool.name))
    return [name for _, name in sorted(scores, key=lambda item: (-item[0], item[1]))]
