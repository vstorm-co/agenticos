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
from uuid import UUID

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

    backend: Literal["state", "service"] = Field(
        default="state",
        description=(
            "state: files only, no shell, stored by the platform - works on every "
            "deployment with no extra services. "
            "service: a container or cloud sandbox, on one of the connections this "
            "organization has registered."
        ),
    )
    connection_id: UUID | None = Field(
        default=None,
        description=(
            "Which registered sandbox connection to run on; null takes the "
            "organization's default. An id, never an address or a token - a spec is "
            "exported to a client's git repository, so the only thing it may carry "
            "is a reference. The connection decides whether that is a container on "
            "a host you run or a sandbox in Daytona's cloud."
        ),
    )
    session_scope: Literal["run", "conversation", "channel", "user", "agent"] = Field(
        default="conversation",
        description=(
            "Who shares the workspace, by default on every surface - a binding on "
            "one of the agent's exposures may say otherwise. "
            "run: nobody, a fresh one every turn. "
            "conversation: everyone in that chat - and on Slack a thread is a chat, "
            "so this is per thread there. "
            "channel: everyone in a Slack channel or group chat, threads included; "
            "a direct message still has its own. "
            "user: one person across their chats with this agent, and across "
            "surfaces once they have linked their account. "
            "agent: everyone who talks to this agent - files are shared between "
            "people in the organization."
        ),
    )
    runtime: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Which environment a container-backed workspace runs, named from the "
            "list the connection's service allows. Null takes the connection's "
            "default. An alias, never an image."
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
    # No `secret=` here, and that is the change worth noting: the credential
    # belongs to the *connection*, not to a binding. Two hosts need two tokens,
    # and a key attached per agent could not express that - nor could it be one
    # concept with the Daytona account an organization bills its cloud sandboxes
    # to. A connection carries both.
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
