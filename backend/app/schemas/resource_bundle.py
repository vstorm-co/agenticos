"""Versioned, data-only dependency manifests for selectable resource exports.

Organization UUIDs identify possible destination reuse candidates. Bundle keys
identify entries within a file and never grant access to either organization.
"""

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from app.schemas.base import BaseSchema

type BundleKey = Annotated[
    str, Field(min_length=1, max_length=160, pattern=r"^[a-z_]+/[a-zA-Z0-9_-]+$")
]
type BundlePath = tuple[StrictStr | StrictInt, ...]


class BundleResourceKind(StrEnum):
    AGENT = "agent"
    WORKFLOW = "workflow"
    SKILL = "skill"
    CONTEXT = "context"
    KNOWLEDGE_BASE = "knowledge_base"
    MCP_CONNECTION = "mcp_connection"
    MODEL_PROFILE = "model_profile"
    EMBEDDING_ENDPOINT = "embedding_endpoint"
    SECRET = "secret"
    SANDBOX_CONNECTION = "sandbox_connection"
    TABLE = "table"
    APP = "app"
    PROJECT = "project"
    EXTERNAL_AGENT = "external_agent"
    CHANNEL_BOT = "channel_bot"
    ROUTINE = "routine"
    AGENT_VERSION = "agent_version"
    SKILL_FORK = "skill_fork"
    SKILL_VERSION = "skill_version"
    MEMBER = "member"
    GROUP = "group"
    TELEPHONY_ENDPOINT = "telephony_endpoint"


class BundleContentLayer(StrEnum):
    DEFINITION = "definition"
    SKILL_FILES = "skill_files"
    CONTEXT_CONTENT = "context_content"
    KB_DOCUMENTS = "kb_documents"
    KB_PARSED_TEXT = "kb_parsed_text"
    KB_INDEX = "kb_index"
    TABLE_ROWS = "table_rows"
    APP_ASSETS = "app_assets"
    PROJECT_FILES = "project_files"


class BundleReference(BaseSchema):
    """One schema-declared reference; UUID-shaped application text is not a pin."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    path: BundlePath = Field(min_length=1, max_length=32)
    target: BundleKey
    is_key: bool = False
    destination_field: Literal["id", "version_number"] = "id"

    @model_validator(mode="after")
    def key_identity(self) -> Self:
        if self.is_key and self.destination_field != "id":
            raise ValueError("A dictionary key must reference a resource identity")
        return self

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: BundlePath) -> BundlePath:
        if any(isinstance(part, int) and part < 0 for part in value):
            raise ValueError("Reference indexes must not be negative")
        if any(isinstance(part, str) and not part for part in value):
            raise ValueError("Reference path segments must not be empty")
        return value


class BundleDestination(BaseSchema):
    """Server-resolved identity and version after destination access checks."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    id: UUID
    parent_id: UUID | None = None
    version_number: int | None = Field(default=None, ge=1, strict=True)


class BundleAsset(BaseSchema):
    """A content-addressed archive member and its logical resource filename."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    resource: BundleKey
    layer: BundleContentLayer
    name: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def relative_name(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or "\\" in value
            or "\x00" in value
            or ":" in path.parts[0]
            or any(part in ("", ".", "..") for part in value.split("/"))
        ):
            raise ValueError("Asset names must be relative paths without traversal")
        return value

    @property
    def archive_path(self) -> str:
        return f"assets/{self.sha256}"


class BundleResource(BaseSchema):
    """A reference-only entry or a selected definition, independent of activation."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    key: BundleKey
    kind: BundleResourceKind
    name: str = Field(min_length=1, max_length=512)
    source_id: UUID | None = None
    source_parent_id: UUID | None = None
    source_version: str | None = Field(default=None, max_length=256)
    definition: dict[str, JsonValue] | None = None
    references: tuple[BundleReference, ...] = Field(default=(), max_length=10_000)
    included: frozenset[BundleContentLayer] = frozenset()

    @model_validator(mode="after")
    def consistent_definition(self) -> Self:
        if self.key.split("/", 1)[0] != self.kind.value:
            raise ValueError("Resource key must use its declared kind")
        if (self.definition is not None) != (BundleContentLayer.DEFINITION in self.included):
            raise ValueError("Definition content must match its inclusion selection")
        paths = [(reference.path, reference.is_key) for reference in self.references]
        if len(paths) != len(set(paths)):
            raise ValueError("Resource reference paths must be unique")
        if self.references and self.definition is None:
            raise ValueError("Reference-only entries cannot carry definition paths")
        return self


class ResourceBundle(BaseSchema):
    """The manifest of an AgenticOS bundle; cycles are legal, dangling pins are not."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    format: Literal["agenticos.bundle"] = "agenticos.bundle"
    format_version: Literal[1] = 1
    roots: tuple[BundleKey, ...] = Field(min_length=1, max_length=100)
    resources: tuple[BundleResource, ...] = Field(min_length=1, max_length=10_000)
    assets: tuple[BundleAsset, ...] = Field(default=(), max_length=100_000)

    @model_validator(mode="after")
    def closed_graph(self) -> Self:
        by_key = {resource.key: resource for resource in self.resources}
        if len(by_key) != len(self.resources):
            raise ValueError("Bundle resource keys must be unique")
        if len(self.roots) != len(set(self.roots)) or not set(self.roots).issubset(by_key):
            raise ValueError("Bundle roots must be unique declared resources")
        for resource in self.resources:
            if any(reference.target not in by_key for reference in resource.references):
                raise ValueError("Every reference must target a declared resource")
        names: set[tuple[str, BundleContentLayer, str]] = set()
        sizes: dict[str, int] = {}
        for asset in self.assets:
            owner = by_key.get(asset.resource)
            if owner is None or asset.layer not in owner.included:
                raise ValueError("Assets must belong to a resource's selected content layer")
            identity = (asset.resource, asset.layer, asset.name)
            if identity in names:
                raise ValueError("Logical resource asset names must be unique within a layer")
            names.add(identity)
            if sizes.setdefault(asset.sha256, asset.size_bytes) != asset.size_bytes:
                raise ValueError("Identical content digests must declare identical sizes")
        return self


class BundleSelection(BaseSchema):
    """An explicit set of resources and content layers to include in a download."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    resources: dict[BundleKey, frozenset[BundleContentLayer]] = Field(max_length=10_000)


class BundleImportChoice(BaseSchema):
    """A destination decision, never a claim that a source ID grants access."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    action: Literal["reuse", "create", "skip"]
    destination_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def destination_for_reuse(self) -> Self:
        if (self.action == "reuse") != (self.destination_id is not None):
            raise ValueError("Only reuse must identify a destination resource")
        if self.name is not None and self.action != "create":
            raise ValueError("Only newly created resources may be renamed")
        return self


class BundleImportCreate(BaseSchema):
    """A reviewed data-only import; no publication, execution or paid ingestion."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    operation_id: UUID
    bundle: ResourceBundle
    choices: dict[BundleKey, BundleImportChoice] = Field(max_length=10_000)


class BundleResourceOption(BaseSchema):
    layers: frozenset[BundleContentLayer] = frozenset()
    key: BundleKey
    available: bool
    can_create: bool = False
    reusable_id: UUID | None = None
    reusable_name: str | None = None


class BundlePreview(BaseSchema):
    bundle: ResourceBundle
    options: tuple[BundleResourceOption, ...]


class BundleImportRead(BaseSchema):
    roots: dict[BundleKey, UUID]
    created: dict[BundleKey, UUID]
    reused: dict[BundleKey, UUID]
    skipped: tuple[BundleKey, ...]


class BundleDocumentCreate(BaseSchema):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    text: str = Field(min_length=1, max_length=4 * 1024 * 1024)


class BundleDownloadCreate(BundleSelection):
    file_format: Literal["yaml", "json"] = "yaml"


class BundleDestinationQuery(BaseSchema):
    kind: BundleResourceKind
    parent_id: UUID | None = None
    search: str = Field(default="", max_length=100)
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=100)


class BundleDestinationOption(BaseSchema):
    id: UUID
    name: str


class BundleDestinationList(BaseSchema):
    items: list[BundleDestinationOption]
    total: int
    searchable: bool = True
