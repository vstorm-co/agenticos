"""Which realtime speech models voice conversations may run on (#54).

Shaped like :mod:`app.services.speech_to_text` and for the same reason: a model,
its voices and its sample rates are *data*, so they live in
`app/core/catalog/realtime_models.json`. The pair is a pick from this file and
the key is a vault secret named beside it whose purpose is the provider - the
A+ pattern every voice feature shares (`.dev-agent/54/model-config-decision.md`).
Model profiles are not read: they are what a text run uses.

**Transport is per model.** OpenAI answers the browser's SDP offer itself and
our server runs the sideband (`webrtc`); Gemini, xAI and Azure stream PCM
through our socket (`relay`). Azure is relay-only because its WebRTC hang-up
cannot be verified (Q3).

**Pricing is per model and always numeric.** `worst_case_usd_per_minute` is what
the setup check multiplies by the call cap; `per_minute` models (xAI) are billed
by duration because the price snapshot prices them at $0. A model with no usable
price is not offered, because a call whose cost cannot be computed is a call
whose `cost_limit` would not be enforced.

Azure entries are *base models*: the deployment name is free text on the
agent's Voice section, and the entry it names decides voices and price.

Gemini, xAI and Azure are wired from the providers' documentation and the
library's code and are **not verified live**.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pydantic import TypeAdapter

from app.agents.model_resolver import PROVIDERS
from app.core import catalog
from app.core.secret_kinds import SecretKind

Transport = Literal["webrtc", "relay"]
PricingKind = Literal["tokens", "per_minute"]


@dataclass(frozen=True)
class RealtimePricing:
    """How a call on this model is priced, in numbers the setup check can use."""

    kind: PricingKind
    worst_case_usd_per_minute: Decimal
    usd_per_minute: Decimal | None = None


@dataclass(frozen=True)
class RealtimeModelEntry:
    """One realtime model, as the Voice card renders it and a call is built from."""

    id: str
    name: str
    description: str
    transport: Transport
    input_sample_rate: int
    output_sample_rate: int
    voices: tuple[str, ...]
    default_voice: str
    supports_thinking: bool
    context_window: int
    pricing: RealtimePricing


@dataclass(frozen=True)
class _CatalogEntry:
    provider: str
    models: tuple[RealtimeModelEntry, ...]
    deployment: bool = False


CATALOG: tuple[_CatalogEntry, ...] = catalog.load(
    "realtime_models.json", TypeAdapter(tuple[_CatalogEntry, ...])
)

_EXCLUDED_PREFIXES = ("gpt-live",)
"""Never offered in v1: GPT-Live takes history only at start and cannot be
reconfigured, so a reconnect could not be seeded (spec amendment 14)."""


@dataclass(frozen=True)
class RealtimeProvider:
    """One provider that can hold a voice conversation, with what may be chosen on it."""

    provider: str
    name: str
    secret_kind: SecretKind
    deployment: bool
    models: tuple[RealtimeModelEntry, ...]


def providers_in(entries: tuple[_CatalogEntry, ...]) -> tuple[RealtimeProvider, ...]:
    """Every provider in these catalog entries that this deployment can reach.

    An entry is dropped where the platform does not know the provider or it
    lists no models; a GPT-Live model is dropped by name.
    """
    found: list[RealtimeProvider] = []
    for entry in entries:
        spec = PROVIDERS.get(entry.provider)
        models = tuple(m for m in entry.models if not m.id.startswith(_EXCLUDED_PREFIXES))
        if spec is None or not models:
            continue
        found.append(
            RealtimeProvider(
                provider=spec.id,
                name=spec.name,
                secret_kind=spec.secret_kind,
                deployment=entry.deployment,
                models=models,
            )
        )
    return tuple(found)


_OFFERED = providers_in(CATALOG)
"""Built once: the catalog file and the platform's providers are fixed for the process."""


def providers() -> tuple[RealtimeProvider, ...]:
    """Every provider the catalog offers that this deployment can reach."""
    return _OFFERED


def by_provider(provider: str) -> RealtimeProvider | None:
    """The offering for one provider id, or `None`."""
    return next((entry for entry in providers() if entry.provider == provider), None)


def offered(provider: str, model: str) -> RealtimeModelEntry | None:
    """The catalog entry for this pair, or `None` when it is not offered.

    For Azure, `model` is the base model the deployment runs.
    """
    entry = by_provider(provider)
    if entry is None:
        return None
    return next((candidate for candidate in entry.models if candidate.id == model), None)
