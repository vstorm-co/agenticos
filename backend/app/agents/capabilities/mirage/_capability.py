"""A Mirage virtual terminal for one run: its mounts, opened late and closed after.

Two Mirage workspaces over the same sources rather than one. Mirage judges a
write by the mount's mode, so the read-only view refuses every write by
construction - which is what lets `mirage_explore` run without approval while
`mirage_run`, the same shell over the writable view, sits behind the gate.
Sharing the scratch resource is what makes a file `mirage_run` wrote readable
from `mirage_explore` in the next call.

The author's policy - which commands exist, which paths do not - is Mirage's
own permission profile, so it is enforced by the shell that parses the line
rather than by a second parser here that could read `$(...)` or a pipe
differently.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from mirage import MountMode, Workspace
from mirage.core.github.config import GitHubConfig
from mirage.policy import CommandsBlock, PathsBlock, SessionProfile
from mirage.resource.github.github import GitHubResource
from mirage.resource.ram.ram import RAMResource
from pydantic import SecretStr
from pydantic_ai import RunContext
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.capabilities import AbstractCapability, WrapRunHandler
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.mirage._toolset import Terminal, build_toolset
from app.agents.capabilities.mirage._tree import MountedTree, tree_resource

SCRATCH = "/scratch/"
_PROFILE = "agent"


@dataclass(frozen=True)
class GitHubMount:
    """One repository, and where in the tree it appears."""

    owner: str
    repo: str
    ref: str | None = None

    @property
    def path(self) -> str:
        return f"/github/{self.owner}/{self.repo}/"


@dataclass
class _Views:
    """The two workspaces of one run - see the module docstring."""

    explore: Workspace
    run: Workspace

    async def close(self) -> None:
        await self.explore.close()
        await self.run.close()


def profile(allowed_commands: tuple[str, ...], hidden_paths: tuple[str, ...]) -> SessionProfile:
    """The author's policy as a Mirage permission profile.

    No allowed commands means every command, which is Mirage's own reading of
    an unstated `allow`.
    """
    return SessionProfile(
        commands=CommandsBlock(allow=allowed_commands or None),
        paths=PathsBlock(hide=hidden_paths),
    )


@dataclass
class Mirage(AbstractCapability[AgentDepsT]):
    """A virtual terminal over repositories, platform folders and a scratch folder."""

    repositories: tuple[GitHubMount, ...] = ()
    # Knowledge bases and sync sources, resolved by the runner for this run.
    trees: tuple[MountedTree, ...] = ()
    scratch: bool = True
    allowed_commands: tuple[str, ...] = ()
    hidden_paths: tuple[str, ...] = ()
    # Unsealed from the vault by the factory, and `repr=False` because a
    # dataclass repr is what reaches a log line and every traceback frame.
    token: str = field(default="", repr=False)
    timeout_seconds: int = 60
    max_output_chars: int = 20_000

    _views: _Views | None = field(default=None, init=False, repr=False, compare=False)

    async def for_run(self, ctx: RunContext[AgentDepsT]) -> Mirage[AgentDepsT]:
        # A fresh instance, so one run's scratch folder is never another's.
        return replace(self)

    async def wrap_run(
        self, ctx: RunContext[AgentDepsT], *, handler: WrapRunHandler
    ) -> AgentRunResult[Any]:
        try:
            return await handler()
        finally:
            if self._views is not None:
                await self._views.close()
                self._views = None
            for tree in self.trees:
                await tree.close()

    def get_instructions(self) -> str:
        mounted = [
            f"- {mount.path}: GitHub repository {mount.owner}/{mount.repo}"
            for mount in self.repositories
        ]
        mounted += [f"- {tree.path}: {tree.describe}" for tree in self.trees]
        lines = [
            "You have a virtual terminal (Mirage). These folders are mounted read-only:",
            *mounted,
        ]
        if self.scratch:
            lines.append(
                f"- {SCRATCH}: writable, for your own files; empty at the start of each run"
            )
        lines.append(
            "Use mirage_explore for ls, cat, grep, find, head and wc across them"
            + (", and mirage_run only to write into the scratch folder." if self.scratch else ".")
        )
        # Mirage 0.0.6 reads only the first mount's operands when one line
        # names folders on two mounts, and says nothing about the rest.
        lines.append("To search several folders, grep from / or run one grep per folder.")
        if self.allowed_commands:
            lines.append(f"Only these commands exist: {', '.join(self.allowed_commands)}.")
        return "\n".join(lines)

    def get_toolset(self) -> AbstractToolset[Any]:
        return build_toolset(
            Terminal(
                open_views=self._open,
                timeout_seconds=self.timeout_seconds,
                max_output_chars=self.max_output_chars,
            )
        )

    def _open(self) -> _Views:
        """The run's two workspaces, built on the first command rather than up front.

        Late, because building one is free but a run that never touches the
        terminal should not have opened anything to close. Nothing is fetched
        here either: a repository's tree is read on the first command that needs it.
        """
        if self._views is None:
            config = GitHubConfig(token=SecretStr(self.token))
            sources: dict[str, Any] = {
                mount.path: GitHubResource(
                    config, owner=mount.owner, repo=mount.repo, ref=mount.ref
                )
                for mount in self.repositories
            }
            # One resource per tree, shared by both views, so a listing read in
            # one is not asked for again in the other.
            sources.update({tree.path: tree_resource(tree) for tree in self.trees})
            scratch = RAMResource() if self.scratch else None
            policy = profile(self.allowed_commands, self.hidden_paths)

            def view(mode: MountMode) -> Workspace:
                mounts: dict[str, Any] = {
                    path: (source, MountMode.READ) for path, source in sources.items()
                }
                if scratch is not None:
                    mounts[SCRATCH] = (scratch, mode)
                return Workspace(
                    mounts, mode=MountMode.READ, profiles={_PROFILE: policy}, profile=_PROFILE
                )

            self._views = _Views(explore=view(MountMode.READ), run=view(MountMode.WRITE))
        return self._views
