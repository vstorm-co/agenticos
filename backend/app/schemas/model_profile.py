"""Schemas for provider credentials and model profiles.

No schema here can carry a secret outward: `CredentialRead` exposes only the
four-character hint, and there is deliberately no endpoint that returns a key.

`provider` is a plain string rather than a `Literal`. The platform ships
twenty-odd providers and gains one whenever Pydantic AI does; a literal here
would be a second list to keep in step with the catalog, and the two would
disagree. `GET /providers/catalog` is the list, and the service refuses
anything not in it.
"""

from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.core.secret_kinds import SecretKind
from app.schemas.base import BaseSchema, TimestampSchema


class ProviderInfo(BaseSchema):
    """One selectable provider, as the credential form reads it."""

    id: str
    name: str
    secret_kind: SecretKind = Field(
        description="Which shape of credential this provider needs - see /secrets/kinds"
    )
    supports_base_url: bool = Field(
        description="Whether a custom endpoint can be stored; false means it would be ignored"
    )
    keyless: bool = Field(
        description=(
            "Whether this provider can run with no credential at all. True only for "
            "self-hosted servers, and a keyless credential still has to carry a base_url."
        )
    )


class ProviderCatalog(BaseSchema):
    items: list[ProviderInfo]
    total: int


class ModelProfileCreate(BaseSchema):
    label: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=255)
    secret_id: UUID | None = Field(
        default=None,
        description=(
            "The vault secret this model is keyed by. Required for every provider except "
            "the keyless ones (Ollama, a LiteLLM proxy), where there is nothing to "
            "authenticate against - the service refuses the wrong combination rather than "
            "letting a model that cannot answer be created."
        ),
    )
    base_url: str | None = Field(
        default=None,
        max_length=512,
        description=(
            "Where to send the request, when it is not the provider's public API: a "
            "gateway, a LiteLLM proxy, a model server on this network. Accepted only for "
            "providers whose SDK names an endpoint parameter - see `supports_base_url` on "
            "the provider catalog - and required for a keyless one, which has no public "
            "API to fall back on."
        ),
    )
    params: dict[str, Any] = Field(default_factory=dict)
    allow_byo: bool = False
    fallback_profile_ids: list[UUID] = Field(default_factory=list)


class ModelProfileRead(BaseSchema, TimestampSchema):
    id: UUID
    label: str
    provider: str
    # Nullable on read though required on write: rows written before the vault
    # became the only key store have none, and a read schema describes what is
    # in the database rather than what a new row must contain. The Builder shows
    # such a profile with a "no key" marker, which is the whole point of being
    # able to see it.
    secret_id: UUID | None = None
    model: str
    #: Absent for every profile aimed at the provider's own public API, which is
    #: most of them.
    base_url: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    allow_byo: bool
    fallback_profile_ids: list[str] = Field(default_factory=list)
    context_length: int | None = Field(
        default=None,
        description=(
            "Tokens this model accepts, as its provider's listing said when the profile "
            "was created. Null means not recorded - a profile older than the column, a "
            "provider that publishes no length, or a listing that could not be reached - "
            "and not that the model accepts none."
        ),
    )


class ModelProfileList(BaseSchema):
    items: list[ModelProfileRead]
    total: int


class ProviderModelRead(BaseSchema):
    """One model a provider offers, as the picker renders it."""

    id: str = Field(description="The string sent as `model`, verbatim")
    name: str = Field(description="What to show; falls back to the id")
    context_length: int | None = Field(
        default=None, description="Tokens the model accepts, where the provider says"
    )
    output_modalities: list[str] = Field(
        default_factory=list,
        description=(
            'What the model emits, where its provider states it - `["text"]`, '
            '`["text", "image"]`. Empty means the listing says nothing, which is most of '
            "them: absent is *not* text-only, so a client filtering on it must treat an empty "
            "list as unknown rather than as a refusal."
        ),
    )


class ImageModelRead(BaseSchema):
    """One model that draws."""

    id: str = Field(description="The id stored on the binding")
    name: str = Field(description="What to show")
    description: str = Field(description="When to reach for this one rather than another")


class ImageProviderRead(BaseSchema):
    """One provider that can draw, and what may be chosen on it."""

    provider: str = Field(description="The catalog id, e.g. `openai`")
    name: str = Field(description="What to show")
    models: list[ImageModelRead]


class ImageProviderList(BaseSchema):
    items: list[ImageProviderRead]
    total: int


class SpeechToTextModelRead(BaseSchema):
    """One model that transcribes."""

    id: str = Field(description="The id stored on the bot")
    name: str = Field(description="What to show")
    description: str = Field(description="When to reach for this one rather than another")


class SpeechToTextProviderRead(BaseSchema):
    """One provider that can transcribe, and what may be chosen on it."""

    provider: str = Field(description="The catalog id, e.g. `openai`")
    name: str = Field(description="What to show")
    models: list[SpeechToTextModelRead]


class SpeechToTextProviderList(BaseSchema):
    items: list[SpeechToTextProviderRead]
    total: int


class ProviderModelList(BaseSchema):
    items: list[ProviderModelRead]
    total: int
    source: Literal["live", "curated", "unlisted"] = Field(
        description=(
            "Where the list came from: `live` if the provider answered, `curated` if this "
            "deployment's own list was used - because the provider publishes none, there is "
            "no key to ask with, or the call failed - and `unlisted` if there was neither, "
            "which is the honest answer for a provider this platform cannot enumerate at "
            "all rather than one whose shortlist happened to be empty."
        )
    )
