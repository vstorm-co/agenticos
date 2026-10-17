"""Mirage capability - a virtual terminal over mounted sources, no container."""

import re
from dataclasses import replace
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.mirage._capability import GitHubMount, Mirage
from app.agents.capabilities.mirage._toolset import EXPLORE_DESCRIPTION, RUN_DESCRIPTION
from app.agents.capabilities.mirage._tree import MountedTree, TreeFile, TreeUnavailable
from app.core.exceptions import BadRequestError
from app.core.secret_kinds import (
    GitTokenSecret,
    SecretCondition,
    SecretKind,
    SecretRequirement,
)

__all__ = [
    "MIRAGE_CAPABILITY_ID",
    "MIRAGE_TREES_RESOURCE",
    "Mirage",
    "MirageConfig",
    "MountedTree",
    "TreeFile",
    "TreeUnavailable",
]

MIRAGE_CAPABILITY_ID = "mirage"

# The knowledge-base and sync-source folders of one run, as `MountedTree`s. The
# runner resolves them, because reading a document or a source's credential is
# the database's and the vault's, and a capability must not fetch either.
MIRAGE_TREES_RESOURCE = "mirage_trees"

# `owner/name`, optionally `@ref`: GitHub's own rules for the two names, which is
# also what keeps a value from smuggling a path segment into the API URL.
_REPOSITORY = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}(@[A-Za-z0-9._/-]{1,200})?$")

# A command name, optionally with the subcommand words Mirage matches after it
# (`git log`). No shell syntax: an allow entry names what may run, it is not a line.
_COMMAND = re.compile(r"^[A-Za-z0-9_.+-]+( [A-Za-z0-9_.+-]+)*$")

# Where the token is sent. Mirage reads a repository through GitHub's REST API,
# so a token sealed for any other host is one this capability must not hand over.
_GITHUB_HOSTS = ("github.com", "api.github.com")


class MirageConfig(BaseModel):
    """What the agent's virtual terminal mounts, and what it may run there.

    Every source is read-only: Mirage reads a repository through the GitHub API,
    a knowledge base through its parsed text and a sync source through the
    platform's connector, and none of them can be written back. The scratch
    folder is the one place the agent may write, and it lasts as long as the run.
    """

    github: bool = Field(
        default=False,
        title="GitHub repositories",
        description="Mount the repositories listed below. Needs a GitHub token from the vault.",
    )
    repositories: list[str] = Field(
        default_factory=list,
        max_length=5,
        title="Repositories",
        description=(
            "Mounted read-only under /github/<owner>/<name>, as owner/name or owner/name@branch."
        ),
    )
    knowledge: bool = Field(
        default=True,
        title="Knowledge bases",
        description=(
            "The agent's knowledge bases, each document as its parsed text under "
            "/knowledge/<base>/."
        ),
    )
    sources: bool = Field(
        default=False,
        title="Knowledge base sources",
        description=(
            "The files behind those knowledge bases' synced sources - S3, Google Drive, "
            "SharePoint, Git - under /sources/<source>/, read with each source's own credential."
        ),
    )
    scratch: bool = Field(
        default=True,
        title="Scratch folder",
        description="A writable /scratch folder for notes and intermediate files, empty each run.",
    )
    timeout_seconds: int = Field(
        default=60,
        ge=5,
        le=600,
        title="Command timeout (seconds)",
        description="How long one command may run before it is stopped.",
        json_schema_extra={"x-advanced": True},
    )
    max_output_chars: int = Field(
        default=20_000,
        ge=1_000,
        le=200_000,
        title="Output limit (characters)",
        description="How much of a command's output reaches the model; the rest is cut.",
        json_schema_extra={"x-advanced": True},
    )
    allowed_commands: list[str] = Field(
        default_factory=list,
        max_length=50,
        title="Allowed commands",
        description=(
            "Only these commands run, e.g. ls, cat, grep. Empty allows every command "
            "the terminal has."
        ),
        json_schema_extra={"x-advanced": True},
    )
    hidden_paths: list[str] = Field(
        default_factory=list,
        max_length=50,
        title="Hidden paths",
        description=(
            "Paths that do not exist for the agent, e.g. /sources/finance or *.env. "
            "Hidden from listings and refused to every command."
        ),
        json_schema_extra={"x-advanced": True},
    )

    @field_validator("repositories")
    @classmethod
    def _repositories(cls, value: list[str]) -> list[str]:
        cleaned = [entry.strip() for entry in value if entry.strip()]
        for entry in cleaned:
            if not _REPOSITORY.match(entry):
                raise ValueError(f"'{entry}' is not owner/name or owner/name@branch")
        if len({entry.split("@")[0].lower() for entry in cleaned}) != len(cleaned):
            raise ValueError("A repository is listed twice")
        return cleaned

    @field_validator("allowed_commands")
    @classmethod
    def _commands(cls, value: list[str]) -> list[str]:
        cleaned = [entry.strip() for entry in value if entry.strip()]
        for entry in cleaned:
            if not _COMMAND.match(entry):
                raise ValueError(f"'{entry}' is not a command name, e.g. grep or git log")
        return cleaned

    @field_validator("hidden_paths")
    @classmethod
    def _hidden(cls, value: list[str]) -> list[str]:
        cleaned = [entry.strip() for entry in value if entry.strip()]
        for entry in cleaned:
            # Mirage reads an absolute entry as a subtree and a bare one as a
            # name pattern anywhere; `docs/x` is neither, and it would hide
            # nothing while the setting said it did.
            if ("/" in entry and not entry.startswith("/")) or ".." in entry.split("/"):
                raise ValueError(f"'{entry}' is not an absolute path or a file name pattern")
        return cleaned

    @model_validator(mode="after")
    def _mounts_something(self) -> Self:
        if not (self.github or self.knowledge or self.sources):
            raise ValueError(
                "Mount at least one source: GitHub repositories, knowledge bases or their sources"
            )
        if self.github and not self.repositories:
            raise ValueError("List at least one repository, or turn GitHub repositories off")
        if self.repositories and not self.github:
            # Refused rather than ignored: a list the terminal silently does not
            # mount is a setting that lies about what the agent can read.
            raise ValueError("Turn GitHub repositories on, or remove the repositories")
        return self


def _mounts(config: MirageConfig) -> tuple[GitHubMount, ...]:
    mounts = []
    for entry in config.repositories:
        name, _, ref = entry.partition("@")
        owner, repo = name.split("/")
        mounts.append(GitHubMount(owner=owner, repo=repo, ref=ref or None))
    return tuple(mounts)


@register(
    id=MIRAGE_CAPABILITY_ID,
    name="Virtual terminal (Mirage)",
    category="analysis",
    description=(
        "Explore GitHub repositories, knowledge bases and their sources with ls, grep, cat "
        "and find in a virtual terminal - no container to start."
    ),
    tools=(
        CapabilityToolInfo(id="mirage_explore", description=EXPLORE_DESCRIPTION),
        CapabilityToolInfo(id="mirage_run", description=RUN_DESCRIPTION, side_effecting=True),
    ),
    config_schema=MirageConfig,
    secret=SecretRequirement(
        kind=SecretKind.GIT_TOKEN,
        # Whenever repositories are mounted, public ones included: Mirage reads a
        # repository through GitHub's API and sends a token with every request,
        # so an empty one answers 401. Knowledge bases and their sources need
        # none here - a source's credential is the one it syncs with.
        description="A GitHub token that can read the repositories, sealed for github.com",
        required_when=SecretCondition(field="github", equals=("true",)),
    ),
)
def _build(ctx: CapabilityBuildContext) -> AbstractCapability[object]:
    config = ctx.config if isinstance(ctx.config, MirageConfig) else MirageConfig()
    terminal: Mirage[object] = Mirage(
        trees=tuple(ctx.resources.get(MIRAGE_TREES_RESOURCE, ())),
        scratch=config.scratch,
        allowed_commands=tuple(config.allowed_commands),
        hidden_paths=tuple(config.hidden_paths),
        timeout_seconds=config.timeout_seconds,
        max_output_chars=config.max_output_chars,
    )
    if not config.github:
        return terminal
    secret = ctx.secret
    if not isinstance(secret, GitTokenSecret):
        # The registry refuses a binding whose required secret is missing; this
        # is the same refusal for one whose kind it was not asked to check.
        raise BadRequestError(
            message="The virtual terminal needs a GitHub token from the vault",
            details={"capability_id": "mirage"},
        )
    if not any(secret.allows(host, None) for host in _GITHUB_HOSTS):
        # The token goes to api.github.com. One sealed for another host was added
        # for somewhere else, and handing it to GitHub is the leak the host field
        # exists to prevent.
        raise BadRequestError(
            message="The selected token is not sealed for github.com",
            details={"capability_id": "mirage", "host": secret.host},
        )
    return replace(terminal, repositories=_mounts(config), token=secret.token.get_secret_value())
