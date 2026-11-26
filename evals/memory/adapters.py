"""Use isolated scopes on separately configured local competitor services."""

from datetime import datetime
from time import perf_counter

import httpx
from dataset import Query
from pydantic import BaseModel, Field
from retrieval import Evidence, Retrieved


class Mem0Item(BaseModel):
    memory: str
    metadata: dict[str, object] | None = None


class Mem0Response(BaseModel):
    results: list[Mem0Item]


class HindsightItem(BaseModel):
    text: str
    document_id: str | None = None


class HindsightResponse(BaseModel):
    results: list[HindsightItem]


class RetainResponse(BaseModel):
    success: bool
    asynchronous: bool = Field(alias="async")
    items_count: int


def local_url(value: str) -> httpx.URL:
    url = httpx.URL(value)
    if (
        url.scheme not in {"http", "https"}
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or url.userinfo
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise ValueError("Use a loopback HTTP(S) service base URL.")
    return url


def source_dates(query: Query) -> dict[str, datetime]:
    return {session.id: session.date for session in query.sessions}


async def mem0(client: httpx.AsyncClient, query: Query, scope: str, top_k: int) -> Retrieved:
    started = perf_counter()
    for session in query.sessions:
        response = await client.post(
            "/memories",
            json={
                "user_id": scope,
                "messages": [turn.model_dump() for turn in session.turns],
                "metadata": {
                    "source_session": session.id,
                    "source_date": session.date.isoformat(),
                },
            },
        )
        response.raise_for_status()
    indexed = perf_counter()
    response = await client.post(
        "/search",
        json={"query": query.question, "filters": {"user_id": scope}, "top_k": top_k},
    )
    data = Mem0Response.model_validate_json(response.raise_for_status().content)
    retrieved = perf_counter()
    dates = source_dates(query)
    evidence = []
    for row in data.results:
        key = (row.metadata or {}).get("source_session")
        source = key if isinstance(key, str) and key in dates else None
        evidence.append(
            Evidence(
                source_id=source,
                text=row.memory,
                date=dates.get(source) if source else None,
            )
        )
    return Retrieved(evidence, (indexed - started) * 1_000, (retrieved - indexed) * 1_000, None)


async def hindsight(client: httpx.AsyncClient, query: Query, scope: str, top_k: int) -> Retrieved:
    path = f"/v1/default/banks/{scope}/memories"
    started = perf_counter()
    for session in query.sessions:
        response = await client.post(
            path,
            json={
                "async": False,
                "items": [
                    {
                        "content": session.text,
                        "document_id": session.id,
                        "timestamp": session.date.isoformat(),
                    }
                ],
            },
        )
        retained = RetainResponse.model_validate_json(response.raise_for_status().content)
        if not retained.success or retained.asynchronous or retained.items_count != 1:
            raise ValueError("Hindsight did not confirm synchronous retention.")
    indexed = perf_counter()
    response = await client.post(
        f"{path}/recall",
        json={
            "query": query.question,
            "query_timestamp": query.date.isoformat(),
            "max_tokens": 8192,
            "types": ["experience", "world"],
        },
    )
    data = HindsightResponse.model_validate_json(response.raise_for_status().content)
    retrieved = perf_counter()
    dates = source_dates(query)
    evidence = []
    for row in data.results[:top_k]:
        source = row.document_id if row.document_id in dates else None
        evidence.append(
            Evidence(
                source_id=source,
                text=row.text,
                date=dates.get(source) if source else None,
            )
        )
    return Retrieved(evidence, (indexed - started) * 1_000, (retrieved - indexed) * 1_000, None)
