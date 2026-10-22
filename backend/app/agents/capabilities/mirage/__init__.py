"""A virtual terminal over the services an author chooses to mount (#2191).

[Mirage](https://github.com/strukto-ai/mirage) mounts backends - a Drive, a
GitHub repository, a Postgres database, an SSH host - under one tree, and runs a
shell over it that reads each through its own API. An agent then answers "which
contracts mention Acme?" with a `grep` across a Drive folder rather than a
container's minute of start-up, or reads a table the way it reads a file.

The spec names **what** is mounted and **how**: the backend, the folder, read or
write, whether a person approves each write, the backend's own options. It
never names a credential's value - a secret is a vault id, a Google account is
a connected account - and it cannot name an endpoint override or a host the
operator has not allowed (`_backends.py`).

The library is the optional `mirage` extra. This module imports none of it, so
the registry loads on a deployment without the terminal; publish then refuses
an agent bound to it, saying why.
"""

import re
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, field_validator, model_validator

from app.agents.capabilities._registry import CapabilityBuildContext, register
from app.agents.capabilities.mirage._backends import BackendInfo, backend, catalog, config_class
from app.agents.capabilities.mirage._resolved import (
    PREFIX,
    TERMINAL_TOOL_INFOS,
    TERMINAL_TOOLS,
    MountValue,
    ResolvedMount,
    ResolvedTerminal,
)

if TYPE_CHECKING:
    from app.agents.capabilities.mirage._capability import Mirage

__all__ = [
    "MIRAGE_CAPABILITY_ID",
    "MIRAGE_MOUNTS_RESOURCE",
    "PREFIX",
    "TERMINAL_TOOLS",
    "BackendInfo",
    "MirageConfig",
    "MirageMount",
    "MountValue",
    "OrganizationAccount",
    "PersonalAccount",
    "ResolvedMount",
    "ResolvedTerminal",
    "backend",
    "catalog",
]

MIRAGE_CAPABILITY_ID = "mirage"

MIRAGE_MOUNTS_RESOURCE = "mirage_mounts"
"""Where the runner leaves this run's resolved mounts, credentials included.

Resolved outside the capability because a mount's credential is a vault secret or
a connected account, and a capability never reads either. Absent for a preview or
a unit test, where the capability contributes nothing rather than a terminal whose
every folder fails.
"""

MAX_MOUNTS = 10

_FOLDER = re.compile(r"^/[a-z0-9][a-z0-9._-]{0,62}/$")
_COMMAND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


class OrganizationAccount(BaseModel):
    """An account the organization connected, answering for everybody."""

    kind: Literal["organization"] = "organization"
    connection_id: UUID = Field(
        title="Account",
        description="Which of the organization's connected accounts the folder reads.",
    )


class PersonalAccount(BaseModel):
    """Each person's own accounts on the service, found when they talk to the agent.

    A person with several gets one folder per account under the mount, named by
    the account; somebody with none - an API key, a schedule - gets none, and the
    agent is told so.
    """

    kind: Literal["personal"] = "personal"


MountAccount = Annotated[OrganizationAccount | PersonalAccount, Field(discriminator="kind")]


class MirageMount(BaseModel):
    """One folder of the terminal."""

    path: str = Field(
        title="Folder",
        description="Where it appears in the terminal, e.g. /drive/.",
    )
    backend: str = Field(title="Service", description="What the folder reads.")
    mode: Literal["read", "write"] = Field(
        default="read",
        title="Access",
        description="Read only, or the agent may write, edit and delete there too.",
    )
    approve_writes: bool = Field(
        default=True,
        title="Approve each write",
        description="A person approves every write before it happens. Only for a writable folder.",
    )
    options: dict[str, JsonValue] = Field(
        default_factory=dict,
        title="Options",
        description="The service's own settings: a repository, a folder, a host.",
    )
    secrets: dict[str, UUID] = Field(
        default_factory=dict,
        title="Credentials",
        description="A vault secret for each credential the service needs, by field.",
    )
    account: MountAccount | None = Field(
        default=None,
        title="Account",
        description="For a service signed in to with an account: whose.",
    )

    @field_validator("path")
    @classmethod
    def _folder(cls, path: str) -> str:
        if not _FOLDER.match(path):
            raise ValueError(
                "A folder is one lowercase name between slashes, e.g. /drive/ or /team-wiki/"
            )
        return path

    @model_validator(mode="after")
    def _fits_its_backend(self) -> Self:
        info = backend(self.backend)
        if info is None:
            if not catalog():
                raise ValueError("This deployment does not have the virtual terminal installed")
            raise ValueError(f"'{self.backend}' is not a service the terminal can mount")
        if not info.available:
            raise ValueError(f"{info.title} cannot be mounted here: {info.reason}")
        properties = info.options_schema.get("properties", {})
        unknown = sorted(set(self.options) - set(properties))
        if unknown:
            raise ValueError(f"{info.title} has no setting {', '.join(unknown)}")
        _check_credentials(self, info)
        _check_options(self, info)
        return self


def _check_credentials(mount: MirageMount, info: BackendInfo) -> None:
    if info.credential == "google":
        if mount.account is None:
            raise ValueError(f"{info.title} needs an account: the organization's or each person's")
        if mount.secrets:
            raise ValueError(f"{info.title} signs in with an account, not with secrets")
        return
    if mount.account is not None:
        raise ValueError(f"{info.title} does not sign in with an account")
    if info.credential == "microsoft":
        if set(mount.secrets) != {"app"}:
            raise ValueError(f"{info.title} needs the Entra app it signs in as, under 'app'")
        return
    unknown = sorted(set(mount.secrets) - set(info.secret_fields))
    if unknown:
        raise ValueError(f"{info.title} has no credential {', '.join(unknown)}")
    missing = [field for field in info.required_secrets if field not in mount.secrets]
    if missing:
        raise ValueError(f"{info.title} needs a secret for {', '.join(missing)}")


def _check_options(mount: MirageMount, info: BackendInfo) -> None:
    """Build the backend with the author's options, credentials stood in.

    Building is what the run will do, and it opens no connection - a backend
    hydrates on first use - so its refusal is the one an author should read now
    rather than in the first run: the config class's, and the backend's own
    (GitHub needs an owner and a repository, which its config leaves optional).
    """
    if config_class(info.name) is None:
        return
    from mirage.vfs.registry import build_vfs

    stand_in: dict[str, Any] = dict.fromkeys(mount.secrets, "secret")
    if info.credential == "google":
        stand_in |= {"client_id": "id", "client_secret": "secret", "refresh_token": "token"}
    if info.credential == "microsoft":
        stand_in = {"access_token": "token"}
    try:
        build_vfs(info.name, {**mount.options, **stand_in})
    except (ValueError, TypeError) as exc:
        # `VFSConfigError`, a `ValueError`, carries the config class's refusal
        # field by field, without the values.
        raise ValueError(f"{info.title}: {exc}") from None


class MirageConfig(BaseModel):
    """The terminal's folders, and the shell's limits."""

    mounts: list[MirageMount] = Field(
        min_length=1,
        max_length=MAX_MOUNTS,
        title="Folders",
        description="What the terminal mounts, each as a folder.",
    )
    allowed_commands: list[str] = Field(
        default_factory=list,
        max_length=64,
        title="Allowed commands",
        description="Only these commands run, e.g. ls, cat, grep. Empty allows every command.",
    )
    hidden_paths: list[str] = Field(
        default_factory=list,
        max_length=64,
        title="Hidden paths",
        description="Paths the agent cannot see at all, e.g. /drive/HR/.",
    )

    @field_validator("allowed_commands")
    @classmethod
    def _commands(cls, commands: list[str]) -> list[str]:
        for command in commands:
            if not _COMMAND.match(command):
                raise ValueError(f"'{command}' is not a command name")
        return commands

    @field_validator("hidden_paths")
    @classmethod
    def _hidden(cls, paths: list[str]) -> list[str]:
        for path in paths:
            if not path.startswith("/"):
                raise ValueError(f"'{path}' is not an absolute path")
        return paths

    @model_validator(mode="after")
    def _distinct_folders(self) -> Self:
        paths = [mount.path for mount in self.mounts]
        if len(paths) != len(set(paths)):
            raise ValueError("Two folders share a name")
        return self


@register(
    id=MIRAGE_CAPABILITY_ID,
    voice="hand_off",
    name="Virtual terminal",
    category="analysis",
    description=(
        "Read and search the services you mount - Drive, GitHub, Notion, a database - "
        "as folders, with a shell and no container."
    ),
    tools=TERMINAL_TOOL_INFOS,
    config_schema=MirageConfig,
)
def _build(ctx: CapabilityBuildContext) -> Mirage | None:
    """The terminal over the mounts the runner resolved, or nothing without them."""
    terminal = ctx.resources.get(MIRAGE_MOUNTS_RESOURCE)
    if not isinstance(terminal, ResolvedTerminal) or not terminal.mounts:
        return None
    config = ctx.config if isinstance(ctx.config, MirageConfig) else None
    from app.agents.capabilities.mirage._capability import Mirage

    return Mirage(
        mounts=terminal.mounts,
        notes=terminal.notes,
        allowed_commands=tuple(config.allowed_commands) if config else (),
        hidden_paths=tuple(config.hidden_paths) if config else (),
    )
