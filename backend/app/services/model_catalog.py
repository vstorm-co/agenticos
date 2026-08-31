"""What models a provider offers, for the field where a model id is chosen.

Two sources, in this order:

**Live.** Most providers publish a list endpoint, and it is the only source that
knows about the model that shipped this morning. The shapes disagree - the array
is at `data`, `models` or the document root; the id is `id`, `name` or
`model`; Gemini prefixes it with `models/` - so each one is described by a
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
from genai_prices.data_snapshot import get_snapshot
from pydantic import TypeAdapter

from app.core import catalog

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60 * 60
LISTING_TIMEOUT_SECONDS = 6.0

CatalogSource = Literal["live", "curated", "unlisted"]
"""Where a picker's suggestions came from, and it is three answers rather than two.

`live` is the provider's own listing; `curated` is this deployment's short
list, served when the provider cannot be asked. `unlisted` is neither, and it
exists because the difference matters on screen: seven providers publish no
listing this platform can read *and* have no curated entry, so they answered
`([], "curated")` - a dropdown saying the provider offers nothing, about a
provider that offers plenty. `unlisted` says the platform cannot enumerate
this one and the id has to be typed, which is true (#923).
"""


@dataclass(frozen=True, slots=True)
class CatalogModel:
    """One model, as a picker needs it."""

    id: str
    name: str
    context_length: int | None = None
    # What the model emits, where its provider says so - `("text",)`,
    # `("text", "image")`. Empty when the listing carries no such field, which is
    # most of them: absent means "not stated", never "text only", because a
    # picker that filtered on a guess would hide models that do work.
    output_modalities: tuple[str, ...] = ()


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
    # is public - true only of OpenRouter and a local Ollama.
    auth_header: str | None = None
    auth_template: str = "{key}"
    extra_headers: dict[str, str] = field(default_factory=dict)
    # Stripped from every id. Gemini answers `models/gemini-3.6-flash` and
    # expects `gemini-3.6-flash` back.
    id_prefix: str = ""
    # Dotted path to a list of what the model emits, where the listing says.
    # OpenRouter and the Hugging Face router both answer
    # `architecture.output_modalities`; nobody else states it at all.
    modalities_path: str | None = None


# Loaded from data rather than written out here. Every field is declarative - a
# URL, three JSON paths, an auth header - so adding a provider that publishes a
# list is a catalog entry, not a Python edit. Ten were added by hand before this,
# which is nine more than the point at which that stops being reasonable.
LISTINGS: dict[str, ListingSpec] = catalog.load(
    "model_listings.json", TypeAdapter(dict[str, ListingSpec])
)


@dataclass(frozen=True, slots=True)
class FallbackModel:
    """One curated suggestion: an id and what to call it, and no more.

    Deliberately no context length. `genai-prices` carries one for every model it
    prices and updates itself, so a number written here is a number that goes
    stale silently - and two of them already had: this file said 1,048,576 for
    `gemini-3.6-flash` where the snapshot says 1,000,000, and the same model was
    written twice with two different figures under `google` and `openrouter`.
    """

    id: str
    name: str


# The handful somebody would actually pick, per provider - the fallback for when
# the provider cannot be asked: no key stored yet, an endpoint that does not list,
# a call that failed.
#
# Curated rather than taken from `genai-prices`, and that is a decision worth
# recording, because the library is already a dependency and does list models. It
# is a *price* dataset: it carries `ada` and `babbage` under OpenAI, `claude-2`
# under Anthropic, 690 rows under OpenRouter, and almost nothing is marked
# deprecated - sorted alphabetically, the first thing a picker would offer for
# OpenAI is `ada`. A short current list beats a long misleading one.
#
# What the library *is* used for is the half that rots: every context length comes
# from it at read time, and `test_model_catalog.py` fails when an id here is one
# the snapshot has never heard of - which is how a typo or a retired model is
# caught rather than shipped as a dropdown the provider refuses.
CURATED: dict[str, tuple[FallbackModel, ...]] = catalog.load(
    "curated_models.json", TypeAdapter(dict[str, tuple[FallbackModel, ...]])
)


def priced_model(provider: str, model_id: str) -> Any | None:
    """This model as `genai-prices` knows it, or None where it has no row for it.

    Two questions come off this and they are not the same one: whether the model
    exists at all, and whether anybody recorded how much context it takes. A
    curated id the snapshot has never heard of is a typo or a retirement, which is
    a build failure; a known model with no window is simply not recorded, and the
    capability resolves one itself.

    The provider ids differ in a handful of places - the snapshot writes `x-ai`
    where the platform writes `xai` - so the alias table is part of the lookup
    rather than a caller's problem. An OpenRouter id *is* `<provider>/<model>`, and
    the snapshot prices those rows under the provider rather than under the
    namespaced spelling.
    """
    if provider == "openrouter" and "/" in model_id:
        upstream, _, bare = model_id.partition("/")
        return priced_model(upstream, bare)

    snapshot_provider = _PRICE_PROVIDER_ALIASES.get(provider, provider)
    for entry in get_snapshot().providers:
        if entry.id == snapshot_provider:
            return entry.find_model(model_id)
    return None


def context_window(provider: str, model_id: str) -> int | None:
    """What the price snapshot says this model accepts, where it says anything."""
    model = priced_model(provider, model_id)
    return None if model is None else model.context_window


# Where the price snapshot spells a provider differently from the platform.
_PRICE_PROVIDER_ALIASES = {"xai": "x-ai", "bedrock": "aws", "google_cloud": "google"}


def curated_models(provider: str) -> tuple[CatalogModel, ...]:
    """The fallback list for one provider, with the windows filled in."""
    return tuple(
        CatalogModel(
            id=entry.id, name=entry.name, context_length=context_window(provider, entry.id)
        )
        for entry in CURATED.get(provider, ())
    )


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
        raise TypeError(f"Expected a list at {spec.array_path or '<root>'}")

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
                output_modalities=_modalities(row, spec.modalities_path),
            )
        )
    return sorted(models, key=lambda entry: entry.id)


def _modalities(row: dict[str, Any], path: str | None) -> tuple[str, ...]:
    """What one row says the model emits, or nothing when it does not say.

    Only strings are kept: a listing that answers `[null]` or `[{...}]` for this
    is a listing whose shape has moved, and a picker filtering on the wreckage
    would be worse than one filtering on nothing.
    """
    if path is None:
        return ()
    node: Any = row
    for step in path.split("."):
        if not isinstance(node, dict):
            return ()
        node = node.get(step)
    if not isinstance(node, list):
        return ()
    return tuple(entry for entry in node if isinstance(entry, str) and entry)


_listing_client: httpx.AsyncClient | None = None
_listing_loop: asyncio.AbstractEventLoop | None = None


def _client() -> httpx.AsyncClient:
    """The shared client for provider listing fetches, built once and reused.

    A catalog refresh asks several providers in turn, and a client per call threw
    the connection pool away before it was reused (#1263). Built lazily and
    rebuilt if it was closed; `close_listing_client` closes it at shutdown. The
    timeout rides each request, so one client serves every listing.

    **Rebuilt when the event loop changes, and that is not tidiness.** An
    `AsyncClient` holds connections bound to the loop that opened them, so one
    built by a request and reused by a Prefect flow - or closed at shutdown from
    a different loop - raises `RuntimeError: Event loop is closed` rather than
    answering. It is the same hazard `rag_tasks._ingestion_service` builds
    per-flow engines for (#948); one process here runs several loops, and this
    is the one client shared across all of them.
    """
    global _listing_client, _listing_loop
    loop = asyncio.get_running_loop()
    if _listing_client is None or _listing_client.is_closed or _listing_loop is not loop:
        _listing_client = httpx.AsyncClient()
        _listing_loop = loop
    return _listing_client


async def close_listing_client() -> None:
    """Close the shared listing client at shutdown.

    A client whose loop has already gone has nothing left to release, and
    `aclose` says so by raising. Dropping the reference is the whole of the
    close in that case; raising would take the application's shutdown down with
    it over a socket that is already unusable.
    """
    global _listing_client, _listing_loop
    if _listing_client is not None and not _listing_client.is_closed:
        try:
            await _listing_client.aclose()
        except RuntimeError:
            logger.debug("listing client outlived its event loop; dropping it unclosed")
    _listing_client = None
    _listing_loop = None


async def _fetch(spec: ListingSpec, api_key: str | None) -> list[CatalogModel]:
    headers = dict(spec.extra_headers)
    if spec.auth_header is not None:
        if api_key is None:
            raise ValueError("This provider's listing needs a key")
        headers[spec.auth_header] = spec.auth_template.format(key=api_key)
    response = await _client().get(spec.url, headers=headers, timeout=LISTING_TIMEOUT_SECONDS)
    response.raise_for_status()
    return _read_listing(response.json(), spec)


def _fallback(curated: list[CatalogModel]) -> tuple[list[CatalogModel], CatalogSource]:
    """What to answer when the provider could not be asked, or said nothing.

    One function because there are four such paths - no listing, no key, a call
    that failed, an empty response - and the interesting half is what they all
    do when there is nothing curated either. Nothing to show and nothing to fall
    back on is not "this provider has no models"; it is this platform not being
    able to enumerate them, and `curated` about an empty list claims a shortlist
    that does not exist. `mistral` is exactly this case: it publishes a listing
    and has no curated entry, so a failed call used to answer `curated` with
    nothing in it (#923).
    """
    return (curated, "curated") if curated else ([], "unlisted")


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
    curated = list(curated_models(provider))

    if spec is None or (spec.auth_header is not None and api_key is None):
        return _fallback(curated)

    # Keyed on the provider alone, not on the key: two keys for one provider see
    # the same catalog, and keying on the key would put a secret in a cache key.
    async with _lock:
        entry = _cache.get(provider)
        if entry is not None and time.monotonic() - entry.fetched_at < CACHE_TTL_SECONDS:
            return list(entry.models), "live"

    try:
        models = await _fetch(spec, api_key)
    except Exception:
        # What is said has to match what is answered: for a provider with no
        # curated entry there is no list to fall back to, and a log line during
        # an outage claiming there was is the opposite account of the response.
        logger.warning(
            "Could not list models for %s; %s",
            provider,
            "using the curated list" if curated else "and there is no curated list to fall back to",
        )
        return _fallback(curated)

    if not models:
        return _fallback(curated)

    async with _lock:
        _cache[provider] = _Entry(models=tuple(models), fetched_at=time.monotonic())
    return models, "live"
