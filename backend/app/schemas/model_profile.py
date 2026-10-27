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

from pydantic import Field, computed_field

from app.agents.model_resolver import ModelApi, lacks_key
from app.core.secret_kinds import SecretKind
from app.schemas.base import BaseSchema, TimestampSchema
from app.services.model_outputs import listed_model_outputs


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
    apis: list[ModelApi] = Field(
        description=(
            "The APIs a profile on this provider chooses between - `responses` and `chat` "
            "for the providers that serve both of OpenAI's, empty for every other"
        )
    )
    native_api: ModelApi | None = Field(
        description=(
            "The API a profile gets on the provider's own endpoint when it names none. "
            "With a `base_url` the default is `chat`. Null where `apis` is empty."
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
    api: ModelApi | None = Field(
        default=None,
        description=(
            "Which API the requests go to: `responses` or `chat`. Accepted only for a "
            "provider whose catalog entry lists `apis`, and stored for every profile on "
            "one. Omitted, it is `native_api` without a `base_url` and `chat` with one - "
            "set it for an endpoint that serves the other, such as a regional OpenAI "
            "endpoint, which serves Responses."
        ),
    )
    params: dict[str, Any] = Field(default_factory=dict)
    fallback_profile_ids: list[UUID] = Field(default_factory=list)


class ModelProfileUpdate(BaseSchema):
    """A change to a model profile, applied in place so its id stays (#2478).

    Every agent names its model by profile id, so changing the key or the
    endpoint here moves every agent on the profile at once - the reason to edit
    rather than add a second profile and repoint each agent. The provider and the
    model id are not editable: another model is another profile.

    Partial: only the fields sent change. For `secret_id`, `base_url` and `api`
    an explicit `null` clears the value, under the same rules creation applies;
    `label` and `params` cannot be cleared, and `null` leaves them as they are.
    """

    label: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="A new name, unique in the organization. `null` keeps the current one.",
    )
    secret_id: UUID | None = Field(
        default=None,
        description=(
            "The vault secret to key the model with. It has to be this organization's, "
            "visible to the caller, and stored for the profile's provider. `null` is "
            "accepted only for a keyless provider that keeps an endpoint. A new "
            "`base_url` checks the stored key the same way: the endpoint is where the "
            "key is sent."
        ),
    )
    base_url: str | None = Field(
        default=None,
        max_length=512,
        description=(
            "Where to send the request. `null` returns the profile to the provider's own "
            "API, which a keyless profile with no key cannot do."
        ),
    )
    api: ModelApi | None = Field(
        default=None,
        description=(
            "`responses` or `chat`, for a provider whose catalog entry lists `apis`. "
            "`null` stores the default for the endpoint. Omitted, the stored choice "
            "stays, unless it was the old endpoint's default and `base_url` changes - "
            "then it moves to the new endpoint's default, as on creation."
        ),
    )
    params: dict[str, Any] | None = Field(
        default=None,
        description="Replaces the profile's default model settings. `null` keeps them.",
    )


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
    #: Null for every provider that serves one API.
    api: ModelApi | None = None
    runs_without_key: bool = Field(
        default=False,
        description=(
            "Whether the profile was saved to run with no key - a self-hosted model or a "
            "gateway that authenticates nothing. False on a profile whose key was deleted, "
            "which `missing_key` then reports."
        ),
    )
    params: dict[str, Any] = Field(default_factory=dict)
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

    @computed_field  # type: ignore[prop-decorator]  # pydantic's documented form
    @property
    def output_modalities(self) -> list[str]:
        """What the model emits - `["text"]`, `["audio"]` - where the platform knows.

        Empty means not known, which is every custom endpoint (a `base_url`,
        whatever the provider) and most models:
        absent is *not* text-only, the same rule as a provider listing's field.
        """
        return list(
            listed_model_outputs(self.provider, self.model, base_url=self.base_url).modalities
        )

    @computed_field  # type: ignore[prop-decorator]  # pydantic's documented form
    @property
    def chat_capable(self) -> bool:
        """Whether an agent can run on this model (#2487).

        False only for a model the platform knows is something else - a
        text-to-speech, transcription, image, video or embedding model. Agent and
        chat model pickers leave those out; the profile stays listed so it can be
        removed. A model it cannot classify is true, and so is every profile
        with a `base_url`: the catalogs describe the vendor's API, not that server.
        """
        return listed_model_outputs(self.provider, self.model, base_url=self.base_url).chat

    @computed_field  # type: ignore[prop-decorator]  # pydantic's documented form
    @property
    def missing_key(self) -> bool:
        """Whether the profile has nothing to authenticate with, so no run can use it (#2478).

        True when its key was deleted from the vault or never set, on any provider
        that needs one. A keyless provider with an endpoint - an Ollama on this
        network - is false. Agent and chat model pickers leave such a profile out
        and mark it "no key"; publish refuses it until it gets a key.
        """
        return lacks_key(
            self.provider,
            secret_id=self.secret_id,
            base_url=self.base_url,
            runs_without_key=self.runs_without_key,
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
    chat_capable: bool = Field(
        default=True,
        description=(
            "Whether an agent can run on this model. False only for one the platform knows "
            "is something else - text to speech, transcription, image, video or embeddings - "
            "which a picker for an agent's model leaves out (#2487). Unknown is true."
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
    languages: list[str] = Field(
        default_factory=list,
        description="ISO-639-1 codes a recording may be pinned to.",
    )


class RealtimeModelRead(BaseSchema):
    """One realtime model, for the Voice card's picker."""

    id: str
    name: str
    description: str
    transport: Literal["webrtc", "relay"]
    voices: list[str]
    default_voice: str
    supports_thinking: bool
    input_sample_rate: int
    output_sample_rate: int


class RealtimeProviderRead(BaseSchema):
    """One provider that can hold a voice conversation, and what may be chosen on it."""

    provider: str
    name: str
    secret_kind: str = Field(description="The vault kind a key for this provider must be")
    deployment: bool = Field(
        description="Whether the model is an Azure deployment name plus a base model"
    )
    models: list[RealtimeModelRead]


class RealtimeProviderList(BaseSchema):
    items: list[RealtimeProviderRead]
    total: int


class TextToSpeechVoiceRead(BaseSchema):
    """One voice a provider offers to every account."""

    id: str = Field(description="The id stored on the binding")
    name: str = Field(description="What to show")
    description: str = Field(description="How it sounds, where the provider says")


class TextToSpeechModelRead(BaseSchema):
    """One model that speaks."""

    id: str = Field(description="The id stored on the binding")
    name: str = Field(description="What to show")
    description: str = Field(description="When to reach for this one rather than another")
    max_characters: int = Field(
        description="The most text one request takes; longer is sent in parts"
    )
    takes_instructions: bool = Field(description="Whether it reads a direction on how to speak")
    voices: list[TextToSpeechVoiceRead] = Field(
        description="The voices this model can speak in. Empty where voices belong to the account"
    )


class TextToSpeechProviderRead(BaseSchema):
    """One provider that can speak, and what may be chosen on it."""

    provider: str = Field(description="The catalog id, e.g. `elevenlabs`")
    name: str = Field(description="What to show")
    formats: list[str] = Field(description="Audio formats it returns, by file extension")
    account_voices: bool = Field(
        description="Whether voices belong to the account, so a binding names one by id"
    )
    models: list[TextToSpeechModelRead]


class TextToSpeechProviderList(BaseSchema):
    items: list[TextToSpeechProviderRead]
    total: int


class VideoModelRead(BaseSchema):
    """One model that makes video, and what it can make."""

    id: str = Field(description="The id stored on the binding")
    name: str = Field(description="What to show")
    description: str = Field(description="When to reach for this one rather than another")
    min_seconds: int = Field(description="The shortest clip it makes")
    max_seconds: int = Field(description="The longest clip it makes")
    duration_choosable: bool = Field(
        description="Whether a call may ask for a length; where not, the model decides"
    )
    aspect_ratios: list[str] = Field(
        description="Aspect ratios it renders; the first is the default"
    )
    resolutions: list[str] = Field(description="Resolutions it renders; the first is the default")
    audio: Literal["always", "optional", "never"] = Field(
        description="Whether a clip carries sound: always, on request, or never"
    )
    first_frame: bool = Field(description="Whether it can start from an image")


class VideoProviderRead(BaseSchema):
    """One provider that can make video, and what may be chosen on it."""

    provider: str = Field(description="The catalog id, e.g. `byteplus`")
    name: str = Field(description="What to show")
    models: list[VideoModelRead]


class VideoProviderList(BaseSchema):
    items: list[VideoProviderRead]
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
