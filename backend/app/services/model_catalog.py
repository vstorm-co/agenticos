"""What models a provider offers, for the field where a model id is chosen.

Two sources, in this order:

**Live.** Most providers publish a list endpoint, and it is the only source that
knows about the model that shipped this morning. The shapes disagree — the array
is at ``data``, ``models`` or the document root; the id is ``id``, ``name`` or
``model``; Gemini prefixes it with ``models/`` — so each one is described by a
:class:`ListingSpec` rather than by a branch.

**Curated.** A short, hand-kept list per provider, used when the provider
publishes nothing (Anthropic-style deployments behind a proxy), when the call
fails, or when there is no key to make it with. It is deliberately small: the
five or six models somebody would actually pick, not a mirror of the catalog.

Neither is authoritative and the field they fill stays free text. A provider
ships a model the morning after this cache was warmed, and a picker that cannot
express "that one" is a picker people work around by editing the spec by hand.

Live listings are cached in-process for an hour. OpenRouter's own edge caches
for five minutes and no provider documents a rate limit for these routes, so an
hour is politeness rather than necessity: the lists move on the order of weeks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60 * 60
LISTING_TIMEOUT_SECONDS = 6.0

CatalogSource = Literal["live", "curated"]


@dataclass(frozen=True, slots=True)
class CatalogModel:
    """One model, as a picker needs it."""

    id: str
    name: str
    context_length: int | None = None


@dataclass(frozen=True, slots=True)
class ListingSpec:
    """How to read one provider's model list.

    Data rather than a function per provider: the calls differ only in a URL, an
    auth header and three JSON paths, and eleven near-identical functions is
    eleven places for the next one to be subtly different.
    """

    url: str
    # Where the array lives in the response body. Empty means the body *is* the
    # array, which is what Together answers with.
    array_path: str
    id_field: str
    name_field: str | None = None
    context_field: str | None = None
    # The header a key goes in, and its value template. None means the endpoint
    # is public — true only of OpenRouter and a local Ollama.
    auth_header: str | None = None
    auth_template: str = "{key}"
    extra_headers: dict[str, str] = field(default_factory=dict)
    # Stripped from every id. Gemini answers `models/gemini-3.6-flash` and
    # expects `gemini-3.6-flash` back.
    id_prefix: str = ""


LISTINGS: dict[str, ListingSpec] = {
    "openrouter": ListingSpec(
        url="https://openrouter.ai/api/v1/models",
        array_path="data",
        id_field="id",
        name_field="name",
        context_field="context_length",
    ),
    "openai": ListingSpec(
        url="https://api.openai.com/v1/models",
        array_path="data",
        id_field="id",
        auth_header="Authorization",
        auth_template="Bearer {key}",
    ),
    "anthropic": ListingSpec(
        url="https://api.anthropic.com/v1/models?limit=100",
        array_path="data",
        id_field="id",
        name_field="display_name",
        context_field="max_input_tokens",
        auth_header="x-api-key",
        extra_headers={"anthropic-version": "2023-06-01"},
    ),
    "google": ListingSpec(
        url="https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
        array_path="models",
        id_field="name",
        name_field="displayName",
        context_field="inputTokenLimit",
        auth_header="x-goog-api-key",
        id_prefix="models/",
    ),
    "mistral": ListingSpec(
        url="https://api.mistral.ai/v1/models",
        array_path="data",
        id_field="id",
        name_field="name",
        context_field="max_context_length",
        auth_header="Authorization",
        auth_template="Bearer {key}",
    ),
    "groq": ListingSpec(
        url="https://api.groq.com/openai/v1/models",
        array_path="data",
        id_field="id",
        context_field="context_window",
        auth_header="Authorization",
        auth_template="Bearer {key}",
    ),
    "deepseek": ListingSpec(
        url="https://api.deepseek.com/models",
        array_path="data",
        id_field="id",
        auth_header="Authorization",
        auth_template="Bearer {key}",
    ),
    "together": ListingSpec(
        url="https://api.together.ai/v1/models",
        array_path="",
        id_field="id",
        name_field="display_name",
        context_field="context_length",
        auth_header="Authorization",
        auth_template="Bearer {key}",
    ),
    "xai": ListingSpec(
        url="https://api.x.ai/v1/models",
        array_path="data",
        id_field="id",
        context_field="context_length",
        auth_header="Authorization",
        auth_template="Bearer {key}",
    ),
    "cohere": ListingSpec(
        url="https://api.cohere.com/v1/models?page_size=200",
        array_path="models",
        id_field="name",
        context_field="context_length",
        auth_header="Authorization",
        auth_template="Bearer {key}",
    ),
}


def _model(model_id: str, name: str, context: int | None = None) -> CatalogModel:
    return CatalogModel(id=model_id, name=name, context_length=context)


# The handful somebody would actually pick, per provider, as of July 2026.
#
# Kept short on purpose. This is a fallback for when the provider cannot be
# asked — no key stored yet, an endpoint that does not list, a call that failed —
# and a mirror of a 339-model catalog would be a mirror that rots. Every id here
# is the string the provider's own API expects, verbatim.
CURATED: dict[str, tuple[CatalogModel, ...]] = {
    "anthropic": (
        _model("claude-opus-5", "Claude Opus 5", 1_000_000),
        _model("claude-sonnet-5", "Claude Sonnet 5", 1_000_000),
        _model("claude-fable-5", "Claude Fable 5", 1_000_000),
        # Dateless and still a pinned snapshot, which is how Anthropic has
        # spelled ids since the 4.6 generation — not an evergreen pointer.
        _model("claude-haiku-4-5", "Claude Haiku 4.5", 200_000),
    ),
    "openai": (
        _model("gpt-5.6-sol", "GPT-5.6 Sol", 1_050_000),
        _model("gpt-5.6-terra", "GPT-5.6 Terra", 1_050_000),
        _model("gpt-5.6-luna", "GPT-5.6 Luna", 1_050_000),
        _model("gpt-5.3-codex", "GPT-5.3 Codex", 400_000),
    ),
    "google": (
        _model("gemini-3.6-flash", "Gemini 3.6 Flash", 1_048_576),
        _model("gemini-3.5-flash", "Gemini 3.5 Flash", 1_048_576),
        _model("gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite", 1_048_576),
        _model("gemini-3.1-pro-preview", "Gemini 3.1 Pro (preview)", 1_048_576),
    ),
    "openrouter": (
        # Namespaced, and not always the provider's own spelling: Anthropic
        # writes `claude-haiku-4-5` and OpenRouter writes `claude-haiku-4.5`.
        _model("anthropic/claude-opus-5", "Claude Opus 5", 1_000_000),
        _model("anthropic/claude-sonnet-5", "Claude Sonnet 5", 1_000_000),
        _model("openai/gpt-5.6-sol", "GPT-5.6 Sol", 1_050_000),
        _model("openai/gpt-5.6-luna", "GPT-5.6 Luna", 1_050_000),
        _model("google/gemini-3.6-flash", "Gemini 3.6 Flash", 1_000_000),
    ),
    "xai": (
        _model("grok-4.5", "Grok 4.5", 500_000),
        _model("grok-4.3", "Grok 4.3", 1_000_000),
    ),
    "deepseek": (
        _model("deepseek-v4-pro", "DeepSeek V4 Pro", 1_000_000),
        _model("deepseek-v4-flash", "DeepSeek V4 Flash", 1_000_000),
    ),
    "groq": (
        _model("openai/gpt-oss-120b", "GPT-OSS 120B", 131_000),
        _model("llama-3.3-70b-versatile", "Llama 3.3 70B", 131_000),
    ),
    # Cohere is deliberately absent: its listing is the only one that carries a
    # real `is_deprecated` flag, so a live answer is strictly better than a
    # hand-kept one — and the 2026 lineup could not be confirmed from Cohere's
    # own docs, which is not a good enough basis for suggesting an id somebody
    # will paste into a spec.
}


@dataclass
class _Entry:
    models: tuple[CatalogModel, ...]
    fetched_at: float


_cache: dict[str, _Entry] = {}
_lock = asyncio.Lock()


def _read_listing(payload: Any, spec: ListingSpec) -> list[CatalogModel]:
    """Turn one provider's response into models, skipping rows it cannot read."""
    rows = payload if spec.array_path == "" else payload.get(spec.array_path)
    if not isinstance(rows, list):
        raise ValueError(f"Expected a list at {spec.array_path or '<root>'}")

    models: list[CatalogModel] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get(spec.id_field)
        if not isinstance(raw, str) or not raw:
            continue
        model_id = raw.removeprefix(spec.id_prefix)
        name = row.get(spec.name_field) if spec.name_field else None
        context = row.get(spec.context_field) if spec.context_field else None
        models.append(
            CatalogModel(
                id=model_id,
                name=name if isinstance(name, str) and name else model_id,
                context_length=context if isinstance(context, int) else None,
            )
        )
    return sorted(models, key=lambda entry: entry.id)


async def _fetch(spec: ListingSpec, api_key: str | None) -> list[CatalogModel]:
    headers = dict(spec.extra_headers)
    if spec.auth_header is not None:
        if api_key is None:
            raise ValueError("This provider's listing needs a key")
        headers[spec.auth_header] = spec.auth_template.format(key=api_key)
    async with httpx.AsyncClient(timeout=LISTING_TIMEOUT_SECONDS) as client:
        response = await client.get(spec.url, headers=headers)
        response.raise_for_status()
        return _read_listing(response.json(), spec)


async def models_for(
    provider: str, *, api_key: str | None = None
) -> tuple[list[CatalogModel], CatalogSource]:
    """What this provider offers, and where the answer came from.

    Never raises for a provider that cannot be reached. The curated list is the
    answer then, because the field this fills is a suggestion box: an empty one
    is a worse outcome than a slightly stale one, and a 502 in a dropdown is the
    worst of the three.

    Args:
        provider: The provider id, as `PROVIDERS` spells it.
        api_key: A key for the provider, where its listing needs one. Only
            OpenRouter's is public.
    """
    spec = LISTINGS.get(provider)
    curated = list(CURATED.get(provider, ()))

    if spec is None or (spec.auth_header is not None and api_key is None):
        return curated, "curated"

    # Keyed on the provider alone, not on the key: two keys for one provider see
    # the same catalog, and keying on the key would put a secret in a cache key.
    async with _lock:
        entry = _cache.get(provider)
        if entry is not None and time.monotonic() - entry.fetched_at < CACHE_TTL_SECONDS:
            return list(entry.models), "live"

    try:
        models = await _fetch(spec, api_key)
    except Exception:
        logger.warning("Could not list models for %s; using the curated list", provider)
        return curated, "curated"

    if not models:
        return curated, "curated"

    async with _lock:
        _cache[provider] = _Entry(models=tuple(models), fetched_at=time.monotonic())
    return models, "live"


def clear_cache() -> None:
    """Forget every cached listing. For tests, and for a deployment that wants
    a fresh answer without a restart."""
    _cache.clear()
