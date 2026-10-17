"""Mirage capability - a virtual terminal over mounted sources, no container."""

import re

from pydantic import BaseModel, Field, field_validator
from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.mirage._capability import GitHubMount, Mirage
from app.agents.capabilities.mirage._toolset import EXPLORE_DESCRIPTION, RUN_DESCRIPTION
from app.core.exceptions import BadRequestError
from app.core.secret_kinds import GitTokenSecret, SecretKind, SecretRequirement

__all__ = ["Mirage", "MirageConfig"]

# `owner/name`, optionally `@ref`: GitHub's own rules for the two names, which is
# also what keeps a value from smuggling a path segment into the API URL.
_REPOSITORY = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}(@[A-Za-z0-9._/-]{1,200})?$")

# Where the token is sent. Mirage reads a repository through GitHub's REST API,
# so a token sealed for any other host is one this capability must not hand over.
_GITHUB_HOSTS = ("github.com", "api.github.com")


class MirageConfig(BaseModel):
    """What the agent's virtual terminal mounts.

    Repositories are always read-only: Mirage reads them through the GitHub API
    and has no way to write one back. The scratch folder is the one place the
    agent may write, and it lasts as long as the run.
    """

    repositories: list[str] = Field(
        default_factory=list,
        min_length=1,
        max_length=5,
        title="GitHub repositories",
        description=(
            "Repositories mounted read-only under /github/<owner>/<name>, as owner/name "
            "or owner/name@branch."
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


def _mounts(config: MirageConfig) -> tuple[GitHubMount, ...]:
    mounts = []
    for entry in config.repositories:
        name, _, ref = entry.partition("@")
        owner, repo = name.split("/")
        mounts.append(GitHubMount(owner=owner, repo=repo, ref=ref or None))
    return tuple(mounts)


@register(
    id="mirage",
    name="Virtual terminal (Mirage)",
    category="analysis",
    description=(
        "Explore GitHub repositories with ls, grep, cat and find in a virtual terminal - "
        "no container to start."
    ),
    tools=(
        CapabilityToolInfo(id="mirage_explore", description=EXPLORE_DESCRIPTION),
        CapabilityToolInfo(id="mirage_run", description=RUN_DESCRIPTION, side_effecting=True),
    ),
    config_schema=MirageConfig,
    secret=SecretRequirement(
        kind=SecretKind.GIT_TOKEN,
        # Always: Mirage reads a repository through GitHub's API and sends a token
        # with every request, so even a public repository answers 401 without one.
        description="A GitHub token that can read the repositories, sealed for github.com",
    ),
)
def _build(ctx: CapabilityBuildContext) -> AbstractCapability[object]:
    config = ctx.config if isinstance(ctx.config, MirageConfig) else MirageConfig()
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
    return Mirage(
        repositories=_mounts(config),
        scratch=config.scratch,
        token=secret.token.get_secret_value(),
        timeout_seconds=config.timeout_seconds,
        max_output_chars=config.max_output_chars,
    )
