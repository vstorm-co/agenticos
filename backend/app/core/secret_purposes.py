"""What a stored secret is *for*.

A vault of keys called "prod" and "the new one" is a vault nobody can use: the
Builder cannot tell which key belongs in a web-search slot, the model picker
cannot tell which providers this organization can actually reach, and the person
adding a key has to remember what they meant a month later.

So every secret names a purpose, and the purposes are a list rather than free
text. Two things fall out of that, and they are the reason this module exists:

*The model picker becomes derivable.* An organization with an OpenRouter key can
be offered OpenRouter's models, without anybody defining a "model profile"
first. What you can reach is what you have keys for.

*A capability can ask for the right key.* Web search needs a Tavily key, not
"an API key" - and the picker can offer the two Tavily secrets rather than all
eleven secrets of that shape.

`custom` is the escape hatch, and it is deliberately last: a purpose nobody
anticipated is a real thing, and refusing to store it would send people back to
environment variables. What it costs is that nothing can suggest it anywhere, so
it is offered as what it is - the answer when none of the others fit.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import TypeAdapter

from app.agents.model_resolver import PROVIDERS
from app.core import catalog
from app.core.secret_kinds import SecretKind


class PurposeCategory(StrEnum):
    """What a purpose lets you do, which is how the vault groups them."""

    MODEL_PROVIDER = "model_provider"
    SEARCH = "search"
    OBSERVABILITY = "observability"
    OTHER = "other"


@dataclass(frozen=True)
class SecretPurpose:
    """One thing a secret can be for."""

    id: str
    label: str
    category: PurposeCategory
    kind: SecretKind
    # Where to get one. Only where the answer is a specific page - a generic
    # "search for your provider's dashboard" link costs a click to find out it
    # is not help.
    help_url: str | None = None
    # What this unlocks, in the words of somebody deciding whether to add it.
    description: str = ""


CUSTOM = "custom"

# Services that are not model providers, loaded from the deployment catalog
# and validated against `SecretPurpose` at import. Each entry is consumed by
# something that names its id - the search ids by the web-research capability,
# `logfire` by an agent's observability spec - so adding one to the file and
# forgetting the consumer leaves a purpose nothing reads, which the drift test
# in tests/test_secret_purposes.py is there to catch.
_SERVICES: tuple[SecretPurpose, ...] = catalog.load(
    "services.json", TypeAdapter(tuple[SecretPurpose, ...])
)

_CUSTOM = SecretPurpose(
    id=CUSTOM,
    label="Something else",
    category=PurposeCategory.OTHER,
    kind=SecretKind.API_KEY,
    description="A key for a service this deployment does not know about yet.",
)


def _from_providers() -> tuple[SecretPurpose, ...]:
    """One purpose per model provider, built from the resolver's own table.

    Generated rather than written out: the provider list is what the runtime
    constructs clients from, and a second hand-maintained copy would drift the
    moment somebody adds a provider - leaving a model nobody can key.
    """
    return tuple(
        SecretPurpose(
            id=spec.id,
            label=spec.name,
            category=PurposeCategory.MODEL_PROVIDER,
            kind=spec.secret_kind,
            description=f"Run models on {spec.name}.",
        )
        for spec in PROVIDERS.values()
    )


def all_purposes() -> list[SecretPurpose]:
    """Every purpose, model providers first and `custom` last.

    The order is the order the vault renders: what most people are here for,
    then the services, then the escape hatch.
    """
    return [*_from_providers(), *_SERVICES, _CUSTOM]


def get(purpose_id: str) -> SecretPurpose | None:
    """One purpose, or None for an id this deployment does not offer."""
    return next((entry for entry in all_purposes() if entry.id == purpose_id), None)
