"""Turning a stored model profile into a live provider client.

The template built one model from environment variables. That cannot work once
several organizations share a deployment: each needs its own key, its own
default, and the ability to rotate either without a redeploy.

So the model is constructed **per run** from the vault:

    profile -> credential -> unsealed secret -> provider client -> Model

There used to be one hand-written builder per provider, and four providers. That
does not scale to the provider set Pydantic AI ships, and it does not need to:
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

The catalog is the subset with credential contracts implemented here. Exposing
another SDK provider also needs those contracts and construction tests. Three
entries (`xai`, `cohere`, `huggingface`) need an SDK of their own, so they are in this repository's
`pydantic-ai-slim` extras: a provider selectable in the Builder that raises
`ImportError` when a run reaches it would be worse than one nobody can pick.

Two entries are not a vendor at all but an API *shape*: `openai_compatible`
and `anthropic_compatible` are the organization's own endpoint, reached at an
address somebody types and a key somebody stores. They are separate entries
because the key is what says where it goes - a key filed under a vendor names
that vendor's public API, which the organization never talks to.

`openai_codex` is the one whose credential changes while it is used. It runs on
a ChatGPT subscription rather than an API key, and its refresh token is spent by
the refresh that replaces it - so the provider is handed somewhere to write the
new pair (:attr:`ResolvedCredential.credential_source`) instead of the pair
itself, and a credential without one is refused rather than built to fail on its
second run.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

import httpx
import httpx2
from openai import AsyncOpenAI
from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.providers import Provider, infer_provider_class
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from app.core.exceptions import BadRequestError
from app.core.secret_kinds import (
    ApiKeySecret,
    AwsCredentialsSecret,
    AzureOpenAISecret,
    GcpServiceAccountSecret,
    NoSecret,
    OpenAIChatGPTSecret,
    OpenAICodexSecret,
    SecretKind,
    SecretValue,
)

if TYPE_CHECKING:
    from pydantic_ai.providers.openai_codex import OpenAICodexCredentialSource

    from app.services.chatgpt_plan import VaultChatGPTCredentials

ModelApi = Literal["chat", "responses", "decisions"]
"""Which of OpenAI's two APIs a profile's requests go to: Chat Completions or Responses."""


def api_for_model(surfaces: tuple[str, ...]) -> ModelApi | None:
    """Prefer Chat Completions, then Responses; leave unknown surfaces unspecified."""
    if "chat" in surfaces:
        return "chat"
    if "responses" in surfaces:
        return "responses"
    return None


def otari_price_identity(model_name: str) -> tuple[str, str] | None:
    """Resolve a direct Otari selector; a routing alias has no fixed upstream price."""
    vendor, separator, model = model_name.partition(":")
    if not separator:
        vendor, separator, model = model_name.partition("/")
    if not separator or not vendor or not model:
        return None
    vendor = {"gemini": "google", "vertexai": "google", "bedrock": "aws", "xai": "x-ai"}.get(
        vendor, vendor
    )
    return vendor, model


ModelRegion = Literal["eu", "eea", "global"]
"""Allowed execution scopes for providers with regional routing."""

STAV_BASE_URL = "https://api.stav.ai/v1"
STAV_REGION_HEADER = "X-Stav-Runs-In"
STAV_DEFAULT_REGION: ModelRegion = "eu"

LLMTR_BASE_URL = "https://llmtr.com/v1"

CHAT_ONLY_PROVIDERS = frozenset({"google", "openrouter", "openai_compatible"})
"""The providers whose generation API is Chat Completions and nothing else.

A provider that speaks one of OpenAI's two APIs has no choice to offer, so the
form draws no API field for it and a profile stores the one it always uses.
"""


@dataclass(frozen=True)
class ProviderSpec:
    """One selectable provider and what it takes to reach it.

    `model_prefix` is what goes in front of the model id for
    :func:`infer_model`, and is only different from `id` where the two
    disagree about which wrapper we want: `openai` infers the Responses API,
    which a profile has to choose rather than inherit, so the prefix names
    the Chat Completions wrapper and the Responses one is built by
    :func:`build_model` when the profile asks for it.

    `native_api` is set for a provider that serves both of OpenAI's APIs, and
    names the one its own endpoint gets when a profile does not say. Neither is
    right everywhere: OpenAI's newest models answer Chat Completions with a 400,
    while most OpenAI-compatible servers behind a `base_url` implement only Chat
    Completions. So a profile on such a provider stores which one it uses.

    `api_prefix` is the path the provider's SDK puts *below* the endpoint, which
    the endpoint therefore must not carry. Anthropic's SDK posts to
    `<endpoint>/v1/messages`, so an endpoint that already ends in `/v1` would
    ask for `/v1/v1/messages`; OpenAI's takes the `/v1` root as the endpoint
    and adds nothing below it. :meth:`endpoint` is where that is applied.
    """

    id: str
    name: str
    secret_kind: SecretKind
    base_url_param: str | None = None
    keyless: bool = False
    requires_base_url: bool = False
    model_prefix: str = ""
    native_api: ModelApi | None = None
    # The first supported region is the default.
    regions: tuple[ModelRegion, ...] = ()
    # Resolve the API from advertised model surfaces rather than a form selection.
    api_from_model: bool = False
    # Served by the bundled subscription gateway: no key and no endpoint on the
    # profile, because each run reaches the running person's own signed-in
    # accounts (`app.services.subscription_accounts.bind_to_person`).
    personal_gateway: bool = False
    # The path the SDK adds below the endpoint, which the endpoint must not carry.
    api_prefix: str = ""

    @property
    def prefix(self) -> str:
        return self.model_prefix or self.id

    @property
    def supports_base_url(self) -> bool:
        return self.base_url_param is not None

    def endpoint(self, base_url: str) -> str:
        """The endpoint as this provider's SDK will use it.

        The SDK adds `api_prefix` itself, so an endpoint that already ends in it
        is trimmed: a base of `https://api.example.com/v1` on an
        Anthropic-compatible server would otherwise ask for `/v1/v1/messages`,
        and the 404 names the path rather than the cause.
        """
        prefix = self.api_prefix
        if not prefix:
            return base_url
        trimmed = base_url.rstrip("/")
        if not trimmed.endswith(prefix):
            return base_url
        return trimmed[: -len(prefix)] or base_url

    @property
    def apis(self) -> tuple[ModelApi, ...]:
        """The APIs a profile may choose between; empty where there is no choice."""
        ordinary: tuple[ModelApi, ...] = (
            ("responses",)
            if self.id == "openai_chatgpt"
            else ("chat",)
            if self.id in CHAT_ONLY_PROVIDERS
            else ("responses", "chat")
            if self.native_api is not None
            else ()
        )
        return (
            (*ordinary, "decisions")
            if self.id in {"openai", "google", "openrouter", "typesafe", "system-one"}
            else ordinary
        )

    def default_api(self, base_url: str | None) -> ModelApi | None:
        """The API a profile gets when it names none.

        The provider's own endpoint gets `native_api`. A `base_url` gets Chat
        Completions, which is the API every OpenAI-compatible server implements;
        a gateway or a regional OpenAI endpoint that serves Responses is a choice
        the profile makes explicitly.
        """
        if self.id == "openai_chatgpt":
            return "responses"
        if self.id in {"typesafe", "system-one"}:
            return "decisions"
        if self.id in CHAT_ONLY_PROVIDERS:
            return "chat"
        if self.native_api is None:
            return None
        return self.native_api if base_url is None else "chat"

    def default_region(self) -> ModelRegion | None:
        """The region a profile gets when it names none; null where there is no choice."""
        return self.regions[0] if self.regions else None


class _StavClient(AsyncOpenAI):
    def _process_response_data[ResponseT](
        self, *, data: object, cast_to: type[ResponseT], response: httpx2.Response
    ) -> ResponseT:
        from app.agents.stav_cost import capture_stav_cost

        capture_stav_cost(data, response.headers)
        return super()._process_response_data(data=data, cast_to=cast_to, response=response)

    async def _prepare_request(self, request: httpx2.Request) -> None:
        await super()._prepare_request(request)
        # Apply after request-level headers, which otherwise override the profile's region.
        if region := self.default_headers.get(STAV_REGION_HEADER):
            request.headers[STAV_REGION_HEADER] = region


class _StavProvider(OpenAIProvider):
    """Stav requests retain the profile's region and the provider-owned client lifecycle."""

    def __init__(self, *, api_key: str, base_url: str, region: ModelRegion) -> None:
        super().__init__(api_key=api_key, base_url=base_url)
        if region != "global":
            self._client = self._client.with_options(default_headers={STAV_REGION_HEADER: region})

    def _create_openai_client(
        self,
        *,
        base_url: str | None,
        api_key: str | Callable[[], Awaitable[str]] | None,
        http_client: httpx2.AsyncClient | httpx.AsyncClient | None,
        default_headers: Mapping[str, str] | None = None,
    ) -> AsyncOpenAI:
        client = self._get_http_client(http_client)
        if not isinstance(client, httpx2.AsyncClient):
            raise TypeError("Stav requires an httpx2 client")
        return _StavClient(
            base_url=base_url, api_key=api_key, http_client=client, default_headers=default_headers
        )


class _EndpointOpenRouterProvider(OpenRouterProvider):
    """Keep OpenRouter's native model handling and SDK-owned client lifecycle."""

    def __init__(self, *, api_key: str, base_url: str) -> None:
        self._endpoint = base_url
        super().__init__(api_key=api_key)

    @property
    def base_url(self) -> str:
        return self._endpoint


def _api_key(
    id: str,  # noqa: A002 - the field is called `id` everywhere it is read
    name: str,
    *,
    base_url_param: str | None = None,
    keyless: bool = False,
    requires_base_url: bool = False,
    model_prefix: str = "",
    native_api: ModelApi | None = None,
    api_prefix: str = "",
) -> ProviderSpec:
    """A provider whose whole credential is one token."""
    return ProviderSpec(
        id=id,
        name=name,
        secret_kind=SecretKind.API_KEY,
        base_url_param=base_url_param,
        keyless=keyless,
        requires_base_url=requires_base_url,
        model_prefix=model_prefix,
        native_api=native_api,
        api_prefix=api_prefix,
    )


COMPATIBLE_ENDPOINTS: dict[str, str] = {
    "minimax": "https://api.minimax.io/v1",
    # The overseas host; mainland China plans use https://api.kimi.com/coding/v1.
    "kimi_code": "https://api.kimi.ai/coding/v1",
    # The international host; mainland China uses https://coding.dashscope.aliyuncs.com/v1.
    "alibaba_coding_plan": "https://coding-intl.dashscope.aliyuncs.com/v1",
    "opencode_go": "https://opencode.ai/inference/go/openai/v1",
    "ollama_cloud": "https://ollama.com/v1",
    "nous_portal": "https://inference-api.nousresearch.com/v1",
    "inception": "https://api.inceptionlabs.ai/v1",
    "cline": "https://api.cline.bot/api/v1",
    "chutes": "https://llm.chutes.ai/v1",
    "synthetic": "https://api.synthetic.new/openai/v1",
    # Required in the profile. Loopback is never reachable from the server, so the
    # example is a gateway service on the deployment's network, allowlisted there.
    "cliproxyapi": "http://cliproxyapi:8317/v1",
}
"""OpenAI-compatible providers built with their own history identity, and the
endpoint each reaches when a profile names none. A plan key works only at its
plan's endpoint, so the default is the plan's, never the vendor's general API.
"""


PROVIDERS: dict[str, ProviderSpec] = {
    spec.id: spec
    for spec in (
        # Hosted providers reached at a fixed endpoint, or at a gateway of the
        # organization's choosing where the SDK allows one.
        _api_key(
            "openai",
            "OpenAI",
            base_url_param="base_url",
            keyless=True,
            model_prefix="openai-chat",
            native_api="responses",
        ),
        _api_key("anthropic", "Anthropic", base_url_param="base_url"),
        _api_key("google", "Google Gemini", base_url_param="base_url"),
        _api_key("typesafe", "TypeSafe (Jev)", base_url_param="base_url"),
        _api_key(
            "system-one",
            "System One API",
            base_url_param="base_url",
            keyless=True,
            requires_base_url=True,
        ),
        _api_key("openrouter", "OpenRouter", base_url_param="base_url"),
        _api_key("github_copilot", "GitHub Copilot", model_prefix="github-copilot"),
        _api_key(
            "otari",
            "Otari",
            base_url_param="base_url",
            model_prefix="openai-chat",
            requires_base_url=True,
        ),
        _api_key("alibaba", "Alibaba Cloud", base_url_param="base_url"),
        _api_key("cerebras", "Cerebras"),
        _api_key("deepseek", "DeepSeek"),
        _api_key("fireworks", "Fireworks AI"),
        _api_key("github", "GitHub Models"),
        _api_key("groq", "Groq"),
        _api_key("heroku", "Heroku AI", base_url_param="base_url"),
        # An OpenAI-compatible gateway that Pydantic AI has no provider for, so it
        # runs on the Chat Completions model at LLMTR's endpoint. `llmtr/...` ids
        # are models hosted in Turkey; the others are routed to their vendors.
        _api_key("llmtr", "LLMTR", model_prefix="openai-chat"),
        _api_key("mistral", "Mistral"),
        _api_key("minimax", "MiniMax", base_url_param="base_url", model_prefix="openai-chat"),
        # Subscription plans that issue a plan key for an OpenAI-compatible
        # endpoint. Each bills the plan, not pay-as-you-go API usage; see
        # `COMPATIBLE_ENDPOINTS` for the default destination of each.
        _api_key(
            "kimi_code", "Kimi Code (plan)", base_url_param="base_url", model_prefix="openai-chat"
        ),
        _api_key(
            "alibaba_coding_plan",
            "Alibaba Coding Plan",
            base_url_param="base_url",
            model_prefix="openai-chat",
        ),
        _api_key(
            "opencode_go", "OpenCode Go", base_url_param="base_url", model_prefix="openai-chat"
        ),
        _api_key(
            "ollama_cloud", "Ollama Cloud", base_url_param="base_url", model_prefix="openai-chat"
        ),
        _api_key(
            "nous_portal", "Nous Portal", base_url_param="base_url", model_prefix="openai-chat"
        ),
        _api_key("inception", "Inception", base_url_param="base_url", model_prefix="openai-chat"),
        _api_key("cline", "Cline", base_url_param="base_url", model_prefix="openai-chat"),
        _api_key("chutes", "Chutes", base_url_param="base_url", model_prefix="openai-chat"),
        _api_key("synthetic", "Synthetic", base_url_param="base_url", model_prefix="openai-chat"),
        # A CLIProxyAPI gateway the operator or person runs: it holds account
        # sign-ins (Antigravity, Grok Build, Kimi, Devin, Muse and others) and
        # serves them as one OpenAI-compatible endpoint behind its client key.
        _api_key(
            "cliproxyapi",
            "CLIProxyAPI (subscription gateway)",
            base_url_param="base_url",
            requires_base_url=True,
            model_prefix="openai-chat",
        ),
        # The gateway that ships with the stack: each person signs in to their
        # own accounts from the console, and a run spends only the runner's.
        ProviderSpec(
            id="subscription_accounts",
            name="Subscription accounts",
            secret_kind=SecretKind.NONE,
            model_prefix="openai-chat",
            personal_gateway=True,
        ),
        _api_key("moonshotai", "Moonshot AI"),
        _api_key("nebius", "Nebius AI Studio"),
        _api_key("ovhcloud", "OVHcloud AI Endpoints"),
        _api_key("sambanova", "SambaNova", base_url_param="base_url"),
        _api_key("together", "Together AI"),
        # An EU inference gateway with an OpenAI-compatible API. Its own entry
        # rather than an OpenAI profile with an endpoint because of the region:
        # a profile chooses EU, EEA or global once, and every request it sends
        # carries that limit. EU first, so a profile that names none stays in it.
        ProviderSpec(
            id="stav",
            name="Stav.ai",
            secret_kind=SecretKind.API_KEY,
            base_url_param="base_url",
            model_prefix="openai-chat",
            native_api="chat",
            regions=(STAV_DEFAULT_REGION, "eea", "global"),
            api_from_model=True,
        ),
        _api_key("vercel", "Vercel AI Gateway"),
        _api_key("zai", "Z.AI", base_url_param="base_url"),
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
        # The organization's own endpoint, spoken to in one of the two API shapes
        # in the wild: OpenAI's Chat Completions and Anthropic's Messages. A
        # server somebody runs, reached at an address they type and a key they
        # store - a gateway, a proxy, a model server on their own network.
        #
        # Their own entries rather than an `openai` or an `anthropic` profile with
        # an endpoint, because the key is the point: a key stored for a custom
        # endpoint says in the vault that it authenticates that endpoint, and
        # not OpenAI's or Anthropic's public API. `openai` with an endpoint
        # already works, but the vault then holds a key named after a vendor
        # the organization never talks to.
        #
        # The Chat Completions one serves that API and nothing else, which is
        # what "OpenAI-compatible" means: vLLM, LM Studio, a LiteLLM proxy and
        # every other server that answers `/chat/completions` and nothing more.
        _api_key(
            "openai_compatible",
            "Custom (OpenAI-compatible)",
            base_url_param="base_url",
            requires_base_url=True,
            model_prefix="openai-chat",
        ),
        # The Anthropic one speaks the Messages API, whose SDK posts to
        # `<endpoint>/v1/messages` - so the endpoint carries no `/v1` of its own.
        # The prefix is `anthropic` because that is the provider class and the
        # model wrapper; the id is the platform's own name for the shape.
        _api_key(
            "anthropic_compatible",
            "Custom (Anthropic-compatible)",
            base_url_param="base_url",
            requires_base_url=True,
            model_prefix="anthropic",
            api_prefix="/v1",
        ),
        # A ChatGPT subscription rather than an API account. Its own entry
        # because the credential is a sign-in that rotates, and because it is
        # billed to one person's subscription rather than to an API key.
        ProviderSpec(
            id="openai_chatgpt",
            name="ChatGPT plan usage (official)",
            secret_kind=SecretKind.OPENAI_CHATGPT,
            model_prefix="openai-chatgpt",
        ),
        ProviderSpec(
            id="openai_codex",
            name="ChatGPT (Codex subscription)",
            secret_kind=SecretKind.OPENAI_CODEX,
            model_prefix="openai-codex",
        ),
        # The three whose credential is genuinely not an API key.
        ProviderSpec(
            id="azure",
            name="Azure OpenAI",
            secret_kind=SecretKind.AZURE_OPENAI,
            # Chat Completions unless a profile chooses otherwise: the Responses
            # API needs a recent `api_version`, and the secret may pin an older one.
            native_api="chat",
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


def lacks_key(
    provider: str,
    *,
    secret_id: UUID | None,
    base_url: str | None,
    runs_without_key: bool,
) -> bool:
    """Whether a profile has nothing to authenticate with and cannot run (#2478).

    A profile with no `secret_id` is usable only when it was saved to run with no
    key (`runs_without_key`) on a keyless provider that names an endpoint: an
    Ollama or a LiteLLM proxy on this network, an OpenAI-compatible gateway that
    authenticates nothing. Every other one is a profile whose key was never set
    or was deleted from the vault, which the foreign key's `ON DELETE SET NULL`
    makes an ordinary state. The provider and the endpoint cannot tell those two
    apart - `keyless` is true of `openai`, and a gateway profile that had a key
    keeps its endpoint when the key goes - which is why the intent is stored.

    One rule for every reader: the profile listing's `missing_key`, publish, and
    the resolver that refuses the run.
    """
    if secret_id is not None:
        return False
    spec = PROVIDERS.get(provider)
    if spec is not None and spec.personal_gateway:
        return False
    return not (runs_without_key and spec is not None and spec.keyless and base_url)


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
    # The profile's, like `base_url`: which API the request goes to on a
    # provider that serves two. `None` for every provider that serves one.
    api: ModelApi | None = None
    # Where a ChatGPT sign-in reads its current tokens from and writes rotated
    # ones back to. `secret` is the pair as it was when the run resolved it,
    # which a refresh in any other run may already have spent.
    credential_source: OpenAICodexCredentialSource | None = None
    chatgpt_source: VaultChatGPTCredentials | None = None
    # The profile's, like `api`: where the requests may run, for a provider that
    # takes a region. `None` for every provider that does not.
    region: ModelRegion | None = None
    # Identity and non-secret routing bind replay to the actual vault destination,
    # including providers whose endpoint lives in a structured credential.
    credential_id: UUID | None = None
    authorization_generation: UUID | None = None
    routing: Mapping[str, str | None] = field(default_factory=dict)
    # Personal Copilot calls validate the connection again before each request.
    token_source: Callable[[], Awaitable[str]] | None = field(default=None, repr=False)


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
    if isinstance(secret, OpenAIChatGPTSecret):
        from app.agents.chatgpt_plan import ChatGPTPlanProvider

        if spec.id != "openai_chatgpt" or credential.chatgpt_source is None:
            raise BadRequestError(
                message="Official ChatGPT usage requires its own durable grant source"
            )
        return ChatGPTPlanProvider(credential.chatgpt_source)
    if isinstance(secret, OpenAICodexSecret):
        return _openai_codex_provider(spec, credential.credential_source)

    if spec.id == "github_copilot":
        from app.agents.copilot import AgenticCopilotProvider

        if credential.base_url is not None:
            raise BadRequestError(message="Copilot requires the fixed GitHub.com gateway")
        if not isinstance(secret, ApiKeySecret):
            raise BadRequestError(message="GitHub Copilot requires an explicit account token")
        return AgenticCopilotProvider(
            secret.api_key.get_secret_value(), token_source=credential.token_source
        )

    if spec.id == "otari":
        from pydantic_ai_otari import DEFAULT_BASE_URL, OtariProvider

        if not isinstance(secret, ApiKeySecret):
            raise BadRequestError(message="Otari requires a vault API key")
        return OtariProvider(
            api_key=secret.api_key.get_secret_value(),
            base_url=credential.base_url or DEFAULT_BASE_URL,
        )

    endpoint: dict[str, str] = {}
    if credential.base_url is not None and spec.base_url_param is not None:
        endpoint[spec.base_url_param] = credential.base_url
    if spec.personal_gateway:
        from pydantic_ai.providers.openai_compatible import OpenAICompatibleProvider

        # Bound to one person's gateway scope by `ModelProfileService.resolve`;
        # anything that skipped it has nobody whose accounts to spend.
        if credential.base_url is None or not isinstance(secret, ApiKeySecret):
            raise BadRequestError(
                message=f"{spec.name} run on the signed-in person's own accounts, "
                "so only a person's own run can use them"
            )
        return OpenAICompatibleProvider(
            spec.id, base_url=credential.base_url, api_key=secret.api_key.get_secret_value()
        )
    if (default := COMPATIBLE_ENDPOINTS.get(spec.id)) is not None:
        from pydantic_ai.providers.openai_compatible import OpenAICompatibleProvider

        if not isinstance(secret, ApiKeySecret):
            raise BadRequestError(message=f"{spec.name} requires a vault API key")
        # A compatible API is a different history authority, not an OpenAI proxy.
        return OpenAICompatibleProvider(
            spec.id,
            base_url=credential.base_url or default,
            api_key=secret.api_key.get_secret_value(),
        )
    provider_class = infer_provider_class(spec.prefix)
    if isinstance(secret, NoSecret):
        return provider_class(**endpoint)
    if not isinstance(secret, ApiKeySecret):
        # Every remaining shape is a bearer key; a secret whose kind does not
        # authenticate a model provider at all (a GitHub OAuth App, say) can only
        # reach here through a mis-wired profile, and must fail loudly rather than
        # be coerced into an `api_key` argument.
        raise BadRequestError(
            message="This secret cannot authenticate a model provider",
            details={"kind": secret.kind.value, "provider": spec.id},
        )
    if spec.id == "stav":
        return _StavProvider(
            api_key=secret.api_key.get_secret_value(),
            base_url=credential.base_url or STAV_BASE_URL,
            region=credential.region or STAV_DEFAULT_REGION,
        )
    if spec.id == "llmtr":
        return OpenAIProvider(api_key=secret.api_key.get_secret_value(), base_url=LLMTR_BASE_URL)
    if spec.id == "openrouter" and credential.base_url is not None:
        return _EndpointOpenRouterProvider(
            api_key=secret.api_key.get_secret_value(), base_url=credential.base_url
        )
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


def _openai_codex_provider(
    spec: ProviderSpec, source: OpenAICodexCredentialSource | None
) -> Provider[Any]:
    """The Codex backend, on tokens it reads from and rotates into the vault.

    Refused without a source rather than built from the resolved pair: the first
    refresh would spend the stored refresh token, the new one would live only in
    this process, and the next run would find the vault holding a token the
    authorization server no longer accepts.
    """
    from pydantic_ai.providers.openai_codex import OpenAICodexProvider

    if source is None:
        raise BadRequestError(
            message="A ChatGPT sign-in can only run where its rotated tokens can be stored",
            details={"provider": spec.id},
        )
    return OpenAICodexProvider(credential_source=source)


PROMPT_CACHE: dict[str, bool] = {"cache": True}
"""Prompt caching, asked of every model unless its profile says not (#2169).

An agent re-sends its instructions, its tool schemas and its whole history on
every request of a run; uncached, a long conversation through OpenRouter sent
300,000 tokens per request with no cache reads, and the account's in-flight
credit ran out mid-run. Pydantic AI's provider-neutral `cache` setting places the
breakpoints - the stable prefix of tools and instructions, and the conversation -
on every provider that takes explicit caching (Anthropic, Bedrock's Anthropic and
Nova models, OpenRouter's Anthropic and Gemini models, OpenAI from GPT-5.6) and is
ignored by one that caches implicitly or not at all. It replaced a table of
Anthropic and OpenRouter flags, which left Bedrock and OpenAI uncached.

A profile turns it off with `cache: false`, or narrows it with a `CacheConfig`
(`{"messages": false}` caches only the prefix). A provider-specific flag a
profile still sets - `anthropic_cache_messages` - takes precedence over this
whole setting for that request, as Pydantic AI defines it.
"""


def build_model(credential: ResolvedCredential, model: str) -> Model:
    """Build a provider client for one model.

    Raises:
        BadRequestError: If the provider has no catalog entry.
    """
    model_client = _build_model(credential, model)
    if credential.provider == "llmtr":
        from app.agents.llmtr import LlmtrModel

        return LlmtrModel(model_client)
    if credential.provider == "stav":
        from app.agents.stav_cost import StavCostModel

        return StavCostModel(model_client)
    return model_client


def _build_model(credential: ResolvedCredential, model: str) -> Model:
    spec = get_provider(credential.provider)
    if is_decision_api(credential.provider, credential.api):
        return _build_decision_model(credential, model)
    if credential.api == "responses":
        # Local for the reason `_build_provider`'s are: a deployment that never
        # configures OpenAI should not import its SDK at startup.
        from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings

        # The Responses API stores each response on OpenAI's side unless told
        # not to, while Chat Completions stores nothing by default - so moving a
        # profile to Responses would otherwise start keeping its conversations
        # with the provider. Pydantic AI carries reasoning between turns as
        # encrypted content rather than by a stored response id, so nothing here
        # needs the stored copy. These are the model's own settings, under the
        # profile's and the agent's: a profile that wants stored responses sets
        # `openai_store` to true.
        return OpenAIResponsesModel(
            model,
            provider=_build_provider(spec, credential),
            settings=OpenAIResponsesModelSettings(openai_store=False),
        )
    if (spec.personal_gateway or spec.id == "cliproxyapi") and model.rsplit("/", 1)[-1].startswith(
        "claude"
    ):
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.profiles.openai import OpenAIModelProfile

        # Anthropic permits at most 20 strict tools. The gateway's OpenAI dialect
        # cannot apply its native adaptive limit; keep all tools and validate
        # their arguments locally, without requesting strict schemas upstream.
        return OpenAIChatModel(
            model,
            provider=_build_provider(spec, credential),
            profile=OpenAIModelProfile(openai_supports_strict_tool_definition=False),
        )
    if spec.prefix == "openrouter":
        return _openrouter_model(spec, credential, model)
    return infer_model(
        f"{spec.prefix}:{model}",
        provider_factory=lambda _: _build_provider(spec, credential),
    )


def is_decision_api(provider: str, api: ModelApi | str | None) -> bool:
    """Decision-only endpoints must not be mistaken for conversational models."""
    return api == "decisions" or provider in {"typesafe", "system-one"}


def _build_decision_model(credential: ResolvedCredential, model: str) -> Model:
    """Use Pydantic AI's native decision transports, preserving the chosen account."""
    from pydantic_ai.models.google_decisions import GoogleDecisionsModel
    from pydantic_ai.models.openai_decisions import OpenAIDecisionsModel
    from pydantic_ai.models.system_one import SystemOneModel
    from pydantic_ai.models.typesafe import TypeSafeModel
    from pydantic_ai.providers.google import GoogleProvider
    from pydantic_ai.providers.system_one import SystemOneProvider
    from pydantic_ai.providers.typesafe import TypeSafeProvider

    if credential.provider in {"openrouter", "system-one"}:
        secret = credential.secret
        if not isinstance(secret, (ApiKeySecret, NoSecret)):
            raise BadRequestError(
                message="A decision endpoint requires an API key or keyless connection"
            )
        endpoint = credential.base_url or "https://openrouter.ai/api/v1"
        return SystemOneModel(
            model,
            provider=SystemOneProvider(
                base_url=endpoint,
                api_key=secret.api_key.get_secret_value()
                if isinstance(secret, ApiKeySecret)
                else "",
            ),
        )
    provider = _build_provider(get_provider(credential.provider), credential)
    if credential.provider == "openai" and isinstance(provider, OpenAIProvider):
        return OpenAIDecisionsModel(model, provider=provider)
    if credential.provider == "google" and isinstance(provider, GoogleProvider):
        return GoogleDecisionsModel(model, provider=provider)
    if credential.provider == "typesafe" and isinstance(provider, TypeSafeProvider):
        return TypeSafeModel(model, provider=provider)
    raise BadRequestError(message="This provider does not serve a supported decision API")


def _openrouter_model(spec: ProviderSpec, credential: ResolvedCredential, model: str) -> Model:
    """An OpenRouter model whose cache breakpoints name no time to live.

    Pydantic AI writes `ttl` into every `cache_control` it sends a Claude model
    through OpenRouter, and OpenRouter forwards it to whichever host serves the
    request. Amazon Bedrock is one of them for most Claude models and refuses the
    field outright ("tools.N.custom.cache_control.ephemeral.ttl: Extra inputs are
    not permitted"), so the same agent failed or answered depending on where
    OpenRouter routed the request. `PROMPT_CACHE` asks for the provider's default
    retention, five minutes on every host, so leaving `ttl` out changes nothing but that.

    A request the provider refuses over the reasoning sent back to it is sent once
    more without it - see `app.agents.openrouter_model`.
    """
    from pydantic_ai.providers.openrouter import OpenRouterModelProfile

    from app.agents.openrouter_model import ReasoningResendOpenRouterModel

    # A partial profile, merged over the one OpenRouter resolves for the model.
    return ReasoningResendOpenRouterModel(
        model,
        provider=_build_provider(spec, credential),
        profile=OpenRouterModelProfile(openrouter_supports_cache_ttl=False),
    )


def build_with_fallbacks(
    primary: tuple[ResolvedCredential, str],
    fallbacks: list[tuple[ResolvedCredential, str]],
) -> Model:
    """Build a model that fails over to the next profile in order.

    A single provider outage should not take an organization's agents down when
    they have a second key or a second provider configured.
    """
    if fallbacks and any(entry[0].provider == "openai_chatgpt" for entry in [primary, *fallbacks]):
        raise BadRequestError(
            message="Official ChatGPT plan usage cannot participate in automatic model fallbacks"
        )
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
