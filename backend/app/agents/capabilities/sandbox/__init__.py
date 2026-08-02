"""Files and a shell — the workspace an agent works in.

`code_execution` computes: a Python evaluator with no network, no filesystem and
a restricted standard library. That restriction is what makes it safe to grant
broadly and what makes it useless for the next thing agents are asked to do —
read a report, write a script, run it, keep the output.

This is that: a real filesystem, and on the backends that have one, a real
shell. The two coexist deliberately. `code_execution` needs no infrastructure
and works on every deployment; this one needs a place to put files, and on the
`state` backend it has no shell at all, so an agent granted both computes with
one and remembers with the other.

The spec chooses a **backend**, never an image, a mount, a network mode or a
ceiling. Those are the operator's, and a spec is authored in a browser by
whoever holds `edit` on an agent - one that could name a Docker image could name
one whose entrypoint mounts the host.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai_backends import ConsoleCapability

from app.agents.capabilities._registry import CapabilityBuildContext, register
from app.agents.capabilities.sandbox._capability import WORKSPACE_TOOLS, build_workspace
from app.agents.capabilities.sandbox._identity import (
    BackendKind,
    SessionScope,
    WorkspaceIdentity,
    WorkspaceScopeUnavailable,
    scope_key,
)
from app.core.secret_kinds import SecretCondition, SecretKind, SecretRequirement

__all__ = [
    "WORKSPACE_BACKEND_RESOURCE",
    "BackendKind",
    "SandboxConfig",
    "SessionScope",
    "WorkspaceIdentity",
    "WorkspaceScopeUnavailable",
    "scope_key",
]

WORKSPACE_BACKEND_RESOURCE = "workspace_backend"
"""Where the runner leaves the backend it opened for this run.

Resolved outside the capability because opening one reads and writes the
database - loading a stored `state` document, recording which session id belongs
to which conversation - and a capability must never reach the database itself.
Absent for a preview or a unit test, where an in-memory workspace that lives and
dies with the run is the honest answer rather than an error.
"""


class SandboxConfig(BaseModel):
    """Which workspace this agent gets, and who shares it.

    Two decisions, and the second is the one worth reading twice: `backend` is
    an infrastructure choice, while `session_scope` is a **data-sharing
    policy**. Getting the first wrong costs a feature; getting the second wrong
    shows one person another person's files.
    """

    backend: Literal["state", "docker", "daytona"] = Field(
        default="state",
        description=(
            "state: files only, no shell, stored by the platform - works on every "
            "deployment with no extra services. "
            "docker: a container per workspace, run by the sandboxd service. "
            "daytona: a cloud sandbox, billed to the organization's own account."
        ),
    )
    session_scope: Literal["run", "conversation", "user", "agent"] = Field(
        default="conversation",
        description=(
            "Who shares the workspace. run: nobody, a fresh one every turn. "
            "conversation: everyone in that chat, group channels included. "
            "user: one person across their chats with this agent. "
            "agent: everyone who talks to this agent - files are shared between "
            "people in the organization."
        ),
    )
    runtime: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Which environment a container-backed workspace runs, named from the "
            "list the deployment allows. Null takes the deployment's default."
        ),
    )
    include_execute: bool = Field(
        default=True,
        description=(
            "Whether the agent may run shell commands. Turning it off leaves the "
            "file tools and removes the shell entirely, rather than gating it."
        ),
    )


@register(
    id="sandbox",
    name="Files & shell",
    category="analysis",
    description="Read, write and run things in a workspace that persists between turns.",
    # Every tool declared, including `execute` when a configuration might not
    # offer it. A tool absent from this list cannot be gated by the approval
    # policy or renamed by a binding, and the dangerous half of that is silent:
    # a workspace whose `execute` nobody declared runs unattended forever.
    #
    # `side_effecting` is per tool because this capability is genuinely two
    # things. One flag would either make the agent ask permission to list a
    # directory, or let it overwrite a file unattended.
    tools=WORKSPACE_TOOLS,
    config_schema=SandboxConfig,
    scopes=("sandbox:execute",),
    # The capability as a whole acts on the world; the four read-only tools say
    # otherwise for themselves. This is what a binding's `approval` falls back
    # to when it says nothing about a particular tool.
    side_effecting=True,
    secret=SecretRequirement(
        kind=SecretKind.API_KEY,
        description="The Daytona API key this organization's sandboxes are billed to",
        # Only Daytona authenticates. A flat requirement would make the backend
        # that needs no account - the one every deployment can run - unusable
        # without inventing a key for it.
        required_when=SecretCondition(field="backend", equals=("daytona",)),
    ),
)
def _build(ctx: CapabilityBuildContext) -> ConsoleCapability:
    """Wrap the backend the runner opened in the library's console toolset.

    The backend arrives through `resources` rather than being built here:
    opening one reads the database, and this runs inside `build_agent`, which
    has no session and must not acquire one.
    """
    config = ctx.config if isinstance(ctx.config, SandboxConfig) else SandboxConfig()
    return build_workspace(
        backend=ctx.resources.get(WORKSPACE_BACKEND_RESOURCE),
        include_execute=config.include_execute,
    )
