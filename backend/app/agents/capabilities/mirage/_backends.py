"""Which Mirage backends an author may mount, and what each one asks for.

Mirage ships a registry of backends, each with a typed config class
(`mirage.vfs.registry.REGISTRY`). The Builder's mount form is built from those
classes, so a backend Mirage adds appears without anyone writing a form - but the
classes describe what the *library* accepts, and three kinds of field in them
must never reach a person editing an agent:

- **Secrets** - every `SecretStr` field: a token, an API key, a DSN with its
  password. The form offers a vault secret for each instead of a text box, and
  the runner unseals it; the spec carries only the secret's id.
- **Endpoint overrides** - `base_url`, `api_base`, `endpoint` and their kin
  point a SaaS backend somewhere other than the SaaS. They exist for testing
  against a fake server, and an author who could set one could send the
  organization's token anywhere.
- **Host-side paths and code** - an SSH `identity_file` read off the API host,
  a refresh callback. Neither is something a spec should be able to name.

Addresses an author does type - an SSH host, a Postgres DSN, an IMAP server -
are kept, and checked against `MIRAGE_ALLOWED_HOSTS` at publish and again when
the mount is built (`_hosts.py`).

A backend is **unavailable** when this deployment cannot run it, with the reason
said rather than the backend left out: an author looking for S3 should read why
it is missing, not conclude the feature does not exist.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any, Literal

from pydantic import BaseModel, SecretStr
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from pydantic_core import core_schema

Credential = Literal["fields", "google", "microsoft", "none"]
"""How a backend authenticates.

`fields` - its own secret fields, each a vault secret. `google` - a connected
Google account. `microsoft` - an Entra app, whose token the runner mints for the
run. `none` - nothing (an in-memory scratch folder).
"""

Group = Literal["files", "mail", "chat", "work", "data", "servers", "scratch"]

_HIDDEN_FIELDS = frozenset(
    {
        "base_url",
        "api_base",
        "endpoint",
        "graph_base_url",
        "refresh_fn",
        "on_refresh_token_rotated",
        "identity_file",
        "known_hosts",
    }
)
"""Endpoint overrides, host paths and callbacks, on every backend that has them."""

_GOOGLE_FIELDS = frozenset({"access_token", "client_id", "client_secret", "refresh_token"})
"""The Google credential fields, which a connected account fills instead."""

_MICROSOFT_FIELDS = frozenset({"access_token"})
"""The Graph token, which the runner mints from the binding's Entra app."""

ADDRESS_FIELDS: Mapping[str, tuple[str, ...]] = {
    "chroma": ("host",),
    "databricks_volume": ("host",),
    "dify": ("base_url",),
    "email": ("imap_host", "smtp_host"),
    "gridfs": ("uri",),
    "jaeger": ("host",),
    "mem0": ("host",),
    "mongodb": ("uri",),
    "nextcloud": ("url",),
    "postgres": ("dsn",),
    "redis": ("url",),
    "ssh": ("host", "hostname"),
}
"""Fields that name a host the deployment will connect to, by backend.

`dify.base_url` is an address rather than an override: Dify is self-hosted as
often as not, and there is no SaaS default to send a token to instead.
"""

_EXPOSED_OVERRIDES: Mapping[str, frozenset[str]] = {"dify": frozenset({"base_url"})}
"""Hidden-by-name fields one backend needs as its address."""

_GROUPS: Mapping[str, Group] = {
    "box": "files",
    "dropbox": "files",
    "gdrive": "files",
    "gdocs": "files",
    "gsheets": "files",
    "gslides": "files",
    "onedrive": "files",
    "sharepoint": "files",
    "nextcloud": "files",
    "hf_buckets": "files",
    "hf_datasets": "files",
    "hf_models": "files",
    "hf_spaces": "files",
    "databricks_volume": "files",
    "gmail": "mail",
    "email": "mail",
    "gcal": "mail",
    "slack": "chat",
    "discord": "chat",
    "github": "work",
    "linear": "work",
    "notion": "work",
    "trello": "work",
    "airtable": "work",
    "wandb": "work",
    "postgres": "data",
    "mongodb": "data",
    "gridfs": "data",
    "redis": "data",
    "chroma": "data",
    "mem0": "data",
    "dify": "data",
    "jaeger": "servers",
    "ssh": "servers",
    "ram": "scratch",
}

_S3_FAMILY = frozenset(
    {
        "s3",
        "r2",
        "gcs",
        "oci",
        "minio",
        "ceph",
        "seaweedfs",
        "wasabi",
        "backblaze",
        "digitalocean",
        "tencent",
        "aliyun",
        "scaleway",
        "qingstor",
        "supabase",
    }
)

UNAVAILABLE: Mapping[str, str] = {
    **dict.fromkeys(
        _S3_FAMILY,
        "Needs aioboto3, which pins boto3 below the version this deployment runs on.",
    ),
    "qdrant": "Its client publishes no build for the Python this deployment runs.",
    "lancedb": "Not installed: it brings pyarrow, which is too heavy for the image.",
    "langfuse": "Not installed: it would change the OpenTelemetry the platform traces with.",
    "disk": "It reads the server's own filesystem.",
    "box": "Box replaces its refresh token on every use, so a stored one stops working.",
}
"""Backends this deployment does not offer, and the sentence an author reads."""

_TITLES: Mapping[str, str] = {
    "gdrive": "Google Drive",
    "gdocs": "Google Docs",
    "gsheets": "Google Sheets",
    "gslides": "Google Slides",
    "gcal": "Google Calendar",
    "gmail": "Gmail",
    "onedrive": "OneDrive",
    "sharepoint": "SharePoint",
    "github": "GitHub",
    "hf_buckets": "Hugging Face buckets",
    "hf_datasets": "Hugging Face datasets",
    "hf_models": "Hugging Face models",
    "hf_spaces": "Hugging Face Spaces",
    "databricks_volume": "Databricks volume",
    "mongodb": "MongoDB",
    "gridfs": "GridFS",
    "postgres": "PostgreSQL",
    "ssh": "SSH",
    "email": "Email (IMAP and SMTP)",
    "wandb": "Weights & Biases",
    "mem0": "Mem0",
    "ram": "Scratch folder",
}


class RedisConfig(BaseModel):
    """`redis` takes raw keyword arguments in Mirage; this is their typed form."""

    url: SecretStr
    key_prefix: str = ""


@dataclass(frozen=True)
class BackendInfo:
    """One backend as the Builder shows it, and as publish validates it."""

    name: str
    title: str
    group: Group
    credential: Credential
    available: bool
    reason: str | None
    options_schema: JsonSchemaValue
    """The fields an author fills, as JSON Schema; secrets and hidden fields removed."""
    secret_fields: tuple[str, ...]
    required_secrets: tuple[str, ...]
    address_fields: tuple[str, ...]


class _Lenient(GenerateJsonSchema):
    """JSON Schema for a config that also accepts a callable.

    Google's `access_token` takes a provider callable, which JSON Schema cannot
    say; the field is hidden from authors anyway, so it is described as nothing
    rather than failing the whole schema.
    """

    def callable_schema(self, schema: core_schema.CallableSchema) -> JsonSchemaValue:
        return {}


def config_class(name: str) -> type[BaseModel] | None:
    """The typed config for a backend, or `None` for one that takes none (`ram`).

    Raises:
        ImportError: The backend's library is not installed here.
        KeyError: No backend has that name.
    """
    if name == "redis":
        return RedisConfig
    from mirage.vfs.registry import REGISTRY, resolve_class

    vfs, config = REGISTRY[name]
    resolve_class(vfs)
    if config is None:
        return None
    resolved = resolve_class(config)
    if not issubclass(resolved, BaseModel):
        raise TypeError(f"{name}'s config is not a pydantic model")
    return resolved


def _credential(name: str) -> Credential:
    if name in {"gcal", "gdocs", "gdrive", "gmail", "gsheets", "gslides"}:
        return "google"
    if name in {"onedrive", "sharepoint"}:
        return "microsoft"
    if name == "ram":
        return "none"
    return "fields"


def _hidden(name: str, credential: Credential) -> frozenset[str]:
    hidden = _HIDDEN_FIELDS - _EXPOSED_OVERRIDES.get(name, frozenset())
    if credential == "google":
        hidden |= _GOOGLE_FIELDS
    if credential == "microsoft":
        hidden |= _MICROSOFT_FIELDS
    return hidden


def _describe(name: str) -> BackendInfo:
    title = _TITLES.get(name, name.replace("_", " ").title())
    group = _GROUPS.get(name, "data")
    credential = _credential(name)
    unavailable = UNAVAILABLE.get(name)
    if unavailable is not None:
        return BackendInfo(name, title, group, credential, False, unavailable, {}, (), (), ())
    try:
        model = config_class(name)
    except ImportError:
        return BackendInfo(
            name, title, group, credential, False, "Its library is not installed.", {}, (), (), ()
        )
    if model is None:
        return BackendInfo(name, title, group, credential, True, None, {}, (), (), ())
    schema = model.model_json_schema(schema_generator=_Lenient)
    properties: dict[str, Any] = schema.get("properties", {})
    required = set(schema.get("required", ()))
    hidden = _hidden(name, credential)
    secrets = tuple(
        field for field, spec in properties.items() if field not in hidden and _is_secret(spec)
    )
    options = {
        field: spec
        for field, spec in properties.items()
        if field not in hidden and field not in secrets
    }
    options_schema = {
        "type": "object",
        "properties": options,
        "required": sorted(required & options.keys()),
        "additionalProperties": False,
    }
    return BackendInfo(
        name=name,
        title=title,
        group=group,
        credential=credential,
        available=True,
        reason=None,
        options_schema=options_schema,
        secret_fields=secrets,
        required_secrets=tuple(field for field in secrets if field in required),
        address_fields=ADDRESS_FIELDS.get(name, ()),
    )


def _is_secret(spec: Mapping[str, Any]) -> bool:
    if spec.get("format") == "password":
        return True
    return any(branch.get("format") == "password" for branch in spec.get("anyOf", ()))


@cache
def catalog() -> tuple[BackendInfo, ...]:
    """Every backend Mirage knows, available ones first, then by title.

    Empty when Mirage itself is not installed - the capability then says so as a
    whole rather than listing fifty backends that all fail.
    """
    try:
        from mirage.vfs.registry import REGISTRY
    except ImportError:
        return ()
    infos = [_describe(name) for name in REGISTRY]
    return tuple(sorted(infos, key=lambda info: (not info.available, info.title.lower())))


def backend(name: str) -> BackendInfo | None:
    """One backend's description, or `None` for a name Mirage does not know."""
    return next((info for info in catalog() if info.name == name), None)
