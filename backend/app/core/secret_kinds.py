"""The shapes a stored secret can have, and how each one is sealed.

A secret is not always a string. An AWS key pair is an id, a secret and a
region; an Azure OpenAI deployment is a key plus an endpoint and an API version;
a Vertex credential is a service account document. Forcing all of them into one
"API key" field produces a form somebody can fill in correctly and still end up
with a credential that fails at the first run - which is why a secret has a
*kind*, and why the kind decides which fields exist.

The kinds are the shapes that actually exist, and no more:

`none`
    Not a secret at all - the marker for an endpoint that needs no credential,
    which is the normal case for a self-hosted model server. It exists so the
    resolver can switch on a total set instead of treating "no credential" as a
    missing value, and it is the answer to "what do you store for Ollama on
    localhost"; an empty string is not, and the vault refuses one.
`api_key`
    One opaque token. All but three of the model providers want exactly this,
    and so does every third-party API a custom capability might call.
`azure_openai`
    Azure routes by deployment endpoint and pins an API version, so both travel
    with the key or the credential is unusable.
`aws_credentials`
    An access key id, a secret access key and a region - plus an optional
    session token for STS. The id is not secret and the secret is; a single
    field cannot express that.
`gcp_service_account`
    The service account JSON. Validated on the way in, because the failure mode
    of a malformed one is an authentication error hours later with nothing
    pointing back at the paste that caused it.
`github_oauth_app`
    A GitHub OAuth App's `client_id` and `client_secret`. The id is public and
    the secret is not - a single field cannot express that, the same reason
    `aws_credentials` is a pair.
`google_oauth_app`
    A Google OAuth client's `client_id` and `client_secret`, for connecting a
    mailbox a trigger reads. The same two fields as GitHub's and a separate kind
    on purpose: a kind names what a credential is *for*.

Two unions, deliberately. :data:`StorableSecret` is what a person can save;
:data:`SecretValue` adds `none`, which the runtime can hold but nobody can
store. That difference is what keeps "a secret with no value" out of the API
schema.
"""

from __future__ import annotations

import json
from dataclasses import replace
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    SecretStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.core.exceptions import BadRequestError
from app.core.vault import SealedSecret, VaultScope, seal, unseal


class SecretKind(StrEnum):
    """Which shape a stored secret has. Part of the API contract and of specs."""

    NONE = "none"
    API_KEY = "api_key"
    AZURE_OPENAI = "azure_openai"
    AWS_CREDENTIALS = "aws_credentials"
    GCP_SERVICE_ACCOUNT = "gcp_service_account"
    GITHUB_OAUTH_APP = "github_oauth_app"
    GOOGLE_OAUTH_APP = "google_oauth_app"


def _reveal(value: SecretStr) -> str:
    return value.get_secret_value()


# A secret field that masks itself in every repr - the way a plaintext key
# usually escapes is a dataclass or a Pydantic model being logged whole - but
# serialises to its real value in JSON, which is the one place it has to: on the
# way into the vault. `model_dump()` still yields the SecretStr, so the accident
# of dumping a model into a log line stays harmless.
SealedStr = Annotated[SecretStr, PlainSerializer(_reveal, when_used="json")]


class _SecretBase(BaseModel):
    """Common configuration for every secret payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @property
    def hint(self) -> str:
        """Four characters an operator can recognise this credential by.

        Taken from the field that identifies the credential rather than from the
        one that authenticates it where the two differ - an AWS access key id is
        public, and showing four characters of it is strictly better than
        showing four of the secret access key.
        """
        raise NotImplementedError


class NoSecret(_SecretBase):
    """No credential at all - a model server reached over the network unauthenticated."""

    kind: Literal[SecretKind.NONE] = SecretKind.NONE

    @property
    def hint(self) -> str:
        return ""


class ApiKeySecret(_SecretBase):
    """One opaque token."""

    kind: Literal[SecretKind.API_KEY] = SecretKind.API_KEY
    api_key: SealedStr = Field(title="API key", description="The token, sealed before storage")

    @property
    def hint(self) -> str:
        return self.api_key.get_secret_value()[-4:]


class AzureOpenAISecret(_SecretBase):
    """An Azure OpenAI deployment: key, endpoint and pinned API version."""

    kind: Literal[SecretKind.AZURE_OPENAI] = SecretKind.AZURE_OPENAI
    api_key: SealedStr = Field(title="API key")
    azure_endpoint: str = Field(
        min_length=1,
        title="Endpoint",
        description="e.g. https://my-resource.openai.azure.com",
    )
    api_version: str = Field(min_length=1, title="API version", description="e.g. 2024-10-21")

    @property
    def hint(self) -> str:
        return self.api_key.get_secret_value()[-4:]


class AwsCredentialsSecret(_SecretBase):
    """An AWS key pair and the region its models are served from."""

    kind: Literal[SecretKind.AWS_CREDENTIALS] = SecretKind.AWS_CREDENTIALS
    aws_access_key_id: str = Field(min_length=1, title="Access key ID")
    aws_secret_access_key: SealedStr = Field(title="Secret access key")
    region_name: str = Field(min_length=1, title="Region", description="e.g. us-east-1")
    aws_session_token: SealedStr | None = Field(
        default=None,
        title="Session token",
        description="Only for temporary STS credentials",
    )

    @property
    def hint(self) -> str:
        # The access key id, not the secret: it is not confidential, and it is
        # what an operator sees in the AWS console next to the same key.
        return self.aws_access_key_id[-4:]


# What a service account document must carry to be usable as one.
_SERVICE_ACCOUNT_FIELDS = ("client_email", "private_key", "project_id")


class GcpServiceAccountSecret(_SecretBase):
    """A Google Cloud service account, as downloaded from the console."""

    kind: Literal[SecretKind.GCP_SERVICE_ACCOUNT] = SecretKind.GCP_SERVICE_ACCOUNT
    service_account_json: SealedStr = Field(
        title="Service account JSON", description="The whole downloaded JSON document"
    )
    location: str | None = Field(
        default=None,
        title="Region",
        description="Vertex region, e.g. europe-west4; omit for the provider default",
    )

    @field_validator("service_account_json")
    @classmethod
    def _is_a_service_account_document(cls, value: SecretStr) -> SecretStr:
        """Refuse anything that is not a service account key, while a form is open.

        A truncated paste or the wrong kind of Google credential is otherwise
        indistinguishable from a working one until a run fails, by which point
        nothing points at the paste.
        """
        try:
            document = json.loads(value.get_secret_value())
        except json.JSONDecodeError as exc:
            raise ValueError("Service account credentials must be the downloaded JSON") from exc
        if not isinstance(document, dict) or document.get("type") != "service_account":
            raise ValueError(
                "This is not a service account key - its 'type' is not service_account"
            )
        missing = [field for field in _SERVICE_ACCOUNT_FIELDS if not document.get(field)]
        if missing:
            raise ValueError(f"Service account key is missing: {', '.join(missing)}")
        return value

    @property
    def document(self) -> dict[str, Any]:
        """The parsed service account, for building a Google credential."""
        parsed: dict[str, Any] = json.loads(self.service_account_json.get_secret_value())
        return parsed

    @property
    def project(self) -> str:
        """The project the service account belongs to, taken from the document.

        Not a separate field: two places to state the project is one place for
        them to disagree, and the document is the one the provider authenticates
        against.
        """
        project: str = self.document["project_id"]
        return project

    @property
    def hint(self) -> str:
        email: str = self.document["client_email"]
        return email[-4:]


class GithubOAuthAppSecret(_SecretBase):
    """A GitHub OAuth App's credentials: a public client id and a secret."""

    kind: Literal[SecretKind.GITHUB_OAUTH_APP] = SecretKind.GITHUB_OAUTH_APP
    client_id: str = Field(
        min_length=1,
        max_length=255,
        title="Client ID",
        description="The OAuth App's client id, e.g. Iv1.0123456789abcdef",
    )
    client_secret: SealedStr = Field(min_length=1, title="Client secret")

    @property
    def hint(self) -> str:
        # The client id, not the secret: it is public, and it is what names the
        # app in the GitHub settings the same key sits next to.
        return self.client_id[-4:]


class GoogleOAuthAppSecret(_SecretBase):
    """A Google OAuth client's credentials: a public client id and a secret.

    The same two fields as a GitHub OAuth App and deliberately a different kind:
    the kind names what a credential is *for*, not what shape it is, so filing a
    mailbox client under GitHub's - which takes the same fields - would group by
    the shape and put the wrong app in the wrong consent flow. Same reasoning as
    #937's split of a Drive service account from Vertex AI's.

    Each organization registers its own client in its own Google project. It is not
    the deployment's `GOOGLE_CLIENT_ID`, which is sign-in and a different thing
    entirely; and a credential at rest goes through the vault, which is the whole
    rule.
    """

    kind: Literal[SecretKind.GOOGLE_OAUTH_APP] = SecretKind.GOOGLE_OAUTH_APP
    client_id: str = Field(
        min_length=1,
        max_length=255,
        title="Client ID",
        description="The OAuth client's id, e.g. 1234-abc.apps.googleusercontent.com",
    )
    client_secret: SealedStr = Field(min_length=1, title="Client secret")

    @property
    def hint(self) -> str:
        # The client id, not the secret: it is public, and it is what names the
        # client in the Google console the same key sits next to.
        return self.client_id[-4:]


StorableSecret = Annotated[
    ApiKeySecret
    | AzureOpenAISecret
    | AwsCredentialsSecret
    | GcpServiceAccountSecret
    | GithubOAuthAppSecret
    | GoogleOAuthAppSecret,
    Field(discriminator="kind"),
]
"""Every shape a person can actually save."""

SecretValue = Annotated[
    NoSecret
    | ApiKeySecret
    | AzureOpenAISecret
    | AwsCredentialsSecret
    | GcpServiceAccountSecret
    | GithubOAuthAppSecret
    | GoogleOAuthAppSecret,
    Field(discriminator="kind"),
]
"""What the runtime holds - :data:`StorableSecret` plus "there is no credential"."""

STORABLE_KINDS: frozenset[SecretKind] = frozenset(SecretKind) - {SecretKind.NONE}

_STORABLE_ADAPTER: TypeAdapter[StorableSecret] = TypeAdapter(StorableSecret)


def seal_secret(
    value: StorableSecret, *, scope: VaultScope, key_version: int | None = None
) -> SealedSecret:
    """Seal a typed secret into one envelope.

    The whole payload is sealed as a single JSON document rather than field by
    field, so a credential cannot be half-rotated and the non-secret fields
    (region, endpoint, API version) cannot be edited without the key that
    belongs with them.
    """
    sealed = seal(value.model_dump_json(), scope=scope, key_version=key_version)
    # The vault's hint is the last four characters of what it sealed, which for
    # a JSON document is punctuation. Each kind knows which of its fields
    # identifies it.
    return replace(sealed, hint=value.hint)


def unseal_secret(
    ciphertext: str, *, kind: SecretKind, scope: VaultScope, key_version: int = 1
) -> StorableSecret:
    """Open an envelope and check it holds the kind the row claims.

    Raises:
        BadRequestError: If the envelope cannot be opened, holds something that
            is not a secret payload, or holds a different kind than the column
            says - which would mean a row was edited underneath the schema.
    """
    value = _STORABLE_ADAPTER.validate_json(
        unseal(ciphertext, scope=scope, key_version=key_version)
    )
    if value.kind is not kind:
        raise BadRequestError(
            message="Stored secret does not match its recorded kind",
            details={"recorded": kind.value, "sealed": value.kind.value},
        )
    return value


class SecretKindInfo(BaseModel):
    """One kind as the Builder and the Settings forms render it.

    Served from the API so the frontend generates its forms from the same schema
    the backend validates against, rather than from a second list that drifts.
    """

    model_config = ConfigDict(frozen=True)

    kind: SecretKind
    name: str
    description: str
    json_schema: dict[str, Any]


_KIND_MODELS: dict[SecretKind, type[BaseModel]] = {
    SecretKind.API_KEY: ApiKeySecret,
    SecretKind.AZURE_OPENAI: AzureOpenAISecret,
    SecretKind.AWS_CREDENTIALS: AwsCredentialsSecret,
    SecretKind.GCP_SERVICE_ACCOUNT: GcpServiceAccountSecret,
    SecretKind.GITHUB_OAUTH_APP: GithubOAuthAppSecret,
    SecretKind.GOOGLE_OAUTH_APP: GoogleOAuthAppSecret,
}

_KIND_LABELS: dict[SecretKind, tuple[str, str]] = {
    SecretKind.API_KEY: ("API key", "A single token, sent as-is to the service."),
    SecretKind.AZURE_OPENAI: (
        "Azure OpenAI",
        "A key together with the deployment endpoint and the API version it is pinned to.",
    ),
    SecretKind.AWS_CREDENTIALS: (
        "AWS credentials",
        "An access key id, its secret access key and a region - for Bedrock and other AWS APIs.",
    ),
    SecretKind.GCP_SERVICE_ACCOUNT: (
        "Google service account",
        "The service account JSON downloaded from the Google Cloud console.",
    ),
    SecretKind.GITHUB_OAUTH_APP: (
        "GitHub OAuth App",
        "A GitHub OAuth App's client id and secret, used to connect a GitHub "
        "account for repository webhooks.",
    ),
    SecretKind.GOOGLE_OAUTH_APP: (
        "Google OAuth client",
        "A Google OAuth client's id and secret, used to connect a mailbox an agent is run by.",
    ),
}


def describe_kind(kind: SecretKind) -> str:
    """A kind's own label, for a refusal that names what to add.

    "Add an org-visible Google OAuth client secret in Vault" is actionable where
    "add a google_oauth_app" asks the reader to translate an identifier.
    """
    return _KIND_LABELS[kind][0]


def describe_kinds() -> list[SecretKindInfo]:
    """Every storable kind with the schema its form is generated from."""
    return [
        SecretKindInfo(
            kind=kind,
            name=_KIND_LABELS[kind][0],
            description=_KIND_LABELS[kind][1],
            json_schema=model.model_json_schema(),
        )
        for kind, model in _KIND_MODELS.items()
    ]


class SecretCondition(BaseModel):
    """When a declared secret is actually required, as data rather than code.

    A predicate would be shorter to write and impossible to ship: the Builder
    has to ask for a key at exactly the moments the server will demand one, and
    a lambda cannot cross the wire. So the rule is a value - "this config field
    equals one of these" - evaluated by the same definition on both sides.

    It is deliberately the simplest thing that covers the real case: a capability
    offering several providers where only some authenticate. Anything more
    expressive would be a rules engine nobody can read at a glance.
    """

    model_config = ConfigDict(frozen=True)

    field: str = Field(description="Which config field decides")
    equals: tuple[str, ...] = Field(description="Values of that field that need a secret")

    def is_met(self, config: BaseModel | None) -> bool:
        """Whether this configuration needs the secret."""
        if config is None:
            return False
        return str(getattr(config, self.field, None)) in self.equals


class SecretRequirement(BaseModel):
    """A secret a capability needs, as it declares it in `register(...)`.

    A capability names a *kind*, never an instance: the code says "I need an API
    key", the configuration says which one, and neither the model nor the person
    writing the spec can turn that into a different shape of credential.
    """

    model_config = ConfigDict(frozen=True)

    kind: SecretKind
    description: str = Field(description="What the secret is for, shown next to the picker")
    required_when: SecretCondition | None = Field(
        default=None,
        description=(
            "When this is set, the secret is needed only for the configurations it "
            "names; null means always. Web search takes a key for Tavily and none "
            "for DuckDuckGo, and both the Builder and publish validation read this."
        ),
    )

    @model_validator(mode="after")
    def _a_requirement_is_for_a_real_secret(self) -> SecretRequirement:
        if self.kind is SecretKind.NONE:
            raise ValueError("A capability cannot require the 'none' kind - that is no secret")
        return self
