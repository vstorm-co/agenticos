"""Turning a stored model profile into a live provider client.

The template built one model from environment variables. That cannot work once
several organizations share a deployment: each needs its own key, its own
default, and the ability to rotate either without a redeploy.

So the model is constructed **per run** from the vault:

    profile -> credential -> unsealed secret -> provider client -> Model

There used to be one hand-written builder per provider, and four providers. That
does not scale to the thirty-one Pydantic AI ships, and it does not need to:
:func:`pydantic_ai.providers.infer_provider_class` finds the class and
:func:`pydantic_ai.models.infer_model` picks the right model wrapper for it. What
this module still owns is the part inference cannot know - **which credential
shape a provider wants**. Three of them do not take an API key at all: Azure
needs an endpoint and a pinned API version, Bedrock an AWS key pair and a
region, Vertex a service account. A form that pretended otherwise would collect
a credential that only fails at the first run.

:data:`PROVIDERS` is therefore a catalog rather than a registry of builders: id,
label, the secret kind it wants, and whether it accepts a custom `base_url`.
The Builder's dropdown is generated from it, and
`tests/test_model_profiles.py` constructs every entry, so a provider can never
be selectable in the UI without being constructible at run time.

Four provider names Pydantic AI knows are deliberately absent. `bedrock-mantle`,
`sentence-transformers` and `voyageai` are not chat providers a profile can
point at - the last two are embedding models - and `gateway` does not resolve
to a provider class at all: it is a routing prefix over the others.

Everything else Pydantic AI ships is here. Three of them (`xai`, `cohere`,
`huggingface`) need an SDK of their own, so they are in this repository's
`pydantic-ai-slim` extras: a provider selectable in the Builder that raises
`ImportError` when a run reaches it would be worse than one nobody can pick.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.providers import Provider, infer_provider_class

from app.core.exceptions import BadRequestError
from app.core.secret_kinds import (
    AwsCredentialsSecret,
    AzureOpenAISecret,
    GcpServiceAccountSecret,
    NoSecret,
    SecretKind,
    SecretValue,
)


@dataclass(frozen=True)
class ProviderSpec:
    """One selectable provider and what it takes to reach it.

    `model_prefix` is what goes in front of the model id for
    :func:`infer_model`, and is only different from `id` where the two
    disagree about which wrapper we want: `openai` infers the Responses API,
    which OpenAI-compatible servers (vLLM, LM Studio, a LiteLLM proxy) do not
    implement, so an `openai` profile is built as `openai-chat`.
    """

    id: str
    name: str
    secret_kind: SecretKind
    base_url_param: str | None = None
    keyless: bool = False
    model_prefix: str = ""

    @property
    def prefix(self) -> str:
        return self.model_prefix or self.id

    @property
    def supports_base_url(self) -> bool:
        return self.base_url_param is not None


def _api_key(
    id: str,  # noqa: A002 - the field is called `id` everywhere it is read
    name: str,
    *,
    base_url_param: str | None = None,
    keyless: bool = False,
    model_prefix: str = "",
) -> ProviderSpec:
    """A provider whose whole credential is one token."""
    return ProviderSpec(
        id=id,
        name=name,
        secret_kind=SecretKind.API_KEY,
        base_url_param=base_url_param,
        keyless=keyless,
        model_prefix=model_prefix,
    )


PROVIDERS: dict[str, ProviderSpec] = {
    spec.id: spec
    for spec in (
        # Hosted providers reached at a fixed endpoint, or at a gateway of the
        # organization's choosing where the SDK allows one.
        _api_key(
            "openai", "OpenAI", base_url_param="base_url", keyless=True, model_prefix="openai-chat"
        ),
        _api_key("anthropic", "Anthropic", base_url_param="base_url"),
        _api_key("google", "Google Gemini", base_url_param="base_url"),
        _api_key("openrouter", "OpenRouter"),
        _api_key("alibaba", "Alibaba Cloud", base_url_param="base_url"),
        _api_key("cerebras", "Cerebras"),
        _api_key("deepseek", "DeepSeek"),
        _api_key("fireworks", "Fireworks AI"),
        _api_key("github", "GitHub Models"),
        _api_key("groq", "Groq"),
        _api_key("heroku", "Heroku AI", base_url_param="base_url"),
        _api_key("mistral", "Mistral"),
        _api_key("moonshotai", "Moonshot AI"),
        _api_key("nebius", "Nebius AI Studio"),
        _api_key("ovhcloud", "OVHcloud AI Endpoints"),
        _api_key("sambanova", "SambaNova", base_url_param="base_url"),
        _api_key("together", "Together AI"),
        _api_key("vercel", "Vercel AI Gateway"),
        _api_key("zai", "Z.AI"),
        # `api_host`, not `base_url`: the xAI SDK names it differently, and a
        # credential carrying a base URL for a provider that ignores it is a
        # setting somebody will spend an afternoon on.
        _api_key("xai", "xAI (Grok)", base_url_param="api_host"),
        _api_key("cohere", "Cohere"),
        _api_key("huggingface", "Hugging Face", base_url_param="base_url"),
        # Self-hosted. These are why `keyless` exists: a model server on the
        # deployment's own network usually has nothing to authenticate against.
        _api_key("ollama", "Ollama", base_url_param="base_url", keyless=True),
        _api_key("litellm", "LiteLLM proxy", base_url_param="api_base", keyless=True),
        # The three whose credential is genuinely not an API key.
        ProviderSpec(
            id="azure",
            name="Azure OpenAI",
            secret_kind=SecretKind.AZURE_OPENAI,
        ),
        ProviderSpec(
            id="bedrock",
            name="AWS Bedrock",
            secret_kind=SecretKind.AWS_CREDENTIALS,
        ),
        ProviderSpec(
            id="google_cloud",
            name="Google Vertex AI",
            secret_kind=SecretKind.GCP_SERVICE_ACCOUNT,
            model_prefix="google-cloud",
        ),
    )
}


def get_provider(provider: str) -> ProviderSpec:
    """Look up a provider.

    Raises:
        BadRequestError: If the platform has no entry for it. Reaching this from
            a run means a profile stored a provider the platform cannot
            construct - a data problem worth surfacing plainly rather than an
            AttributeError deep inside a run.
    """
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise BadRequestError(
            message=f"Unsupported model provider: {provider}",
            details={"supported": sorted(PROVIDERS)},
        )
    return spec


@dataclass(frozen=True)
class ResolvedCredential:
    """A decrypted credential ready to build a client with.

    Deliberately not the ORM row: the plaintext must not be attached to
    something a later query might refresh, log or serialize by accident. Every
    secret-bearing field of `secret` is a `SecretStr`, so this whole
    dataclass masks itself in a repr.
    """

    provider: str
    secret: SecretValue
    base_url: str | None = None


def _build_provider(spec: ProviderSpec, credential: ResolvedCredential) -> Provider[Any]:
    """Construct the provider client for one credential.

    The only place that knows a credential's shape. Each branch spreads the
    fields the SDK actually names, which is what makes an AWS key pair reach
    Bedrock as a key pair instead of as a string in an `api_key` argument.

    The three non-API-key branches name their provider class instead of taking
    it from :func:`infer_provider_class`, and that is what makes those keywords
    checked: the inferred type is `type[Provider[Any]]`, an abstract base that
    declares no `__init__`, so nothing verifies the eight keyword names below
    against the SDK that has to accept them. Each of the three secret kinds maps
    to exactly one entry in :data:`PROVIDERS`, so naming the class costs no
    generality. The imports stay local for the reason the inference does them
    lazily: a deployment that never configures Vertex should not pay for the
    Google auth stack at startup.
    """
    secret = credential.secret

    if isinstance(secret, AzureOpenAISecret):
        from pydantic_ai.providers.azure import AzureProvider

        return AzureProvider(
            api_key=secret.api_key.get_secret_value(),
            azure_endpoint=secret.azure_endpoint,
            api_version=secret.api_version,
        )
    if isinstance(secret, AwsCredentialsSecret):
        from pydantic_ai.providers.bedrock import BedrockProvider

        return BedrockProvider(
            aws_access_key_id=secret.aws_access_key_id,
            aws_secret_access_key=secret.aws_secret_access_key.get_secret_value(),
            aws_session_token=(
                secret.aws_session_token.get_secret_value() if secret.aws_session_token else None
            ),
            region_name=secret.region_name,
        )
    if isinstance(secret, GcpServiceAccountSecret):
        return _google_cloud_provider(secret)

    endpoint: dict[str, str] = {}
    if credential.base_url is not None and spec.base_url_param is not None:
        endpoint[spec.base_url_param] = credential.base_url
    provider_class = infer_provider_class(spec.prefix)
    if isinstance(secret, NoSecret):
        return provider_class(**endpoint)
    return provider_class(
        # Every provider reached here takes `api_key`, but the inferred class is
        # the abstract `Provider`, whose only `__init__` is `object`'s.
        # `tests/test_model_profiles.py` constructs each catalog entry, which is
        # what actually holds this true.
        api_key=secret.api_key.get_secret_value(),  # ty: ignore[unknown-argument]
        **endpoint,
    )


def _google_cloud_provider(secret: GcpServiceAccountSecret) -> Provider[Any]:
    """Vertex, authenticated by a service account rather than a key."""
    from google.oauth2 import service_account
    from pydantic_ai.providers.google_cloud import GoogleCloudProvider

    credentials = service_account.Credentials.from_service_account_info(
        secret.document,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    # `location=None` is what the provider does with an omitted one anyway - it
    # falls back to GOOGLE_CLOUD_LOCATION and then to us-central1 - so a stored
    # region can be passed straight through instead of through a kwargs dict.
    return GoogleCloudProvider(
        credentials=credentials, project=secret.project, location=secret.location
    )


def build_model(credential: ResolvedCredential, model: str) -> Model:
    """Build a provider client for one model.

    Raises:
        BadRequestError: If the provider has no catalog entry.
    """
    spec = get_provider(credential.provider)
    return infer_model(
        f"{spec.prefix}:{model}",
        provider_factory=lambda _: _build_provider(spec, credential),
    )


def build_with_fallbacks(
    primary: tuple[ResolvedCredential, str],
    fallbacks: list[tuple[ResolvedCredential, str]],
) -> Model:
    """Build a model that fails over to the next profile in order.

    A single provider outage should not take an organization's agents down when
    they have a second key or a second provider configured.
    """
    model = build_model(*primary)
    if not fallbacks:
        return model
    return FallbackModel(model, *(build_model(*entry) for entry in fallbacks))


@dataclass(frozen=True)
class ModelRequestSpec:
    """What a run needs to build its model, resolved but not yet constructed.

    Produced by :class:`~app.services.model_profile.ModelProfileService` so the
    database work and the client construction stay separable - which is what
    lets tests exercise resolution without a provider SDK.
    """

    profile_id: UUID
    label: str
    provider: str
    model: str
    params: dict[str, Any]
    credential: ResolvedCredential
    fallbacks: list[tuple[ResolvedCredential, str]]
    # Which vault secret this resolved to, for the run to record. The
    # credential itself deliberately does not carry it: `ResolvedCredential`
    # holds plaintext and is kept as narrow as possible, while this is an id a
    # run row, a cost query and an audit trail all want. Null for a keyless
    # provider, where there is no key to attribute spend to.
    secret_id: UUID | None = None
    # How many tokens this model accepts, as its provider's listing said when the
    # profile was created. `None` where it was never recorded, which is what a
    # capability needing the window falls back from - see `compaction`.
    #
    # It travels here rather than being resolved from the model because a
    # `FallbackModel`'s `model_id` is a composite `fallback:...` that resolves to
    # nothing, and the pricing snapshot the alternative reads is wrong for
    # Sonnet-class Anthropic models in the direction that breaks a run (#773).
    context_length: int | None = None

    def build(self) -> Model:
        return build_with_fallbacks((self.credential, self.model), self.fallbacks)
