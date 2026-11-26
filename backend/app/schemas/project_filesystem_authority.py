"""Server-owned terms for a mounted Project view, never accepted from a model."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr

from app.agents.audience import RunAudience
from app.core.permissions import AuthContext


class ProjectFilesystemAuthority(BaseModel):
    """Admission identity retained so every filesystem operation can reauthorize."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actor: AuthContext
    audience: RunAudience
    granted_scopes: frozenset[str]
    conversation_project_id: UUID | None
    conversation_id: UUID | None


@dataclass(frozen=True)
class ProjectFilesystemCredential:
    """A credential handed directly to the sandbox adapter, never to model tools."""

    binding_id: UUID
    token: SecretStr


class ProjectFilesystemBindingRead(BaseModel):
    """The gateway proof a sandbox supervisor verifies before mounting a volume."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_id: UUID
    session_name: str
    tenant: str
    mount_path: Literal["/project"] = "/project"


class ProjectFilesystemLeaseRead(BaseModel):
    """One immutable run directory inside a sandbox's mounted filesystem."""

    id: UUID
    project_id: UUID
    workspace_generation: UUID | None
    path: str
    expires_at: datetime
