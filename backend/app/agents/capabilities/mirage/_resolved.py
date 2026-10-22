"""What the runner hands the terminal, and what the registry declares - without Mirage.

Mirage is the optional `mirage` extra, and the registry imports every capability
at start-up. Everything here is therefore importable on a deployment that does not
have it: the tool declarations the Builder lists, and the resolved mounts the runner
builds. The library is imported where a mount is actually built, which only runs
when an agent bound to this capability runs - and publish has refused that agent
already where the extra is missing.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from pydantic import SecretStr
from pydantic_ai_backends.toolsets.descriptions import TOOL_TEXT

from app.agents.capabilities._registry import CapabilityToolInfo

if TYPE_CHECKING:
    from mirage.workspace.mount.spec import Mount

PREFIX = "mirage"

TERMINAL_TOOLS: tuple[str, ...] = (
    "ls",
    "read_file",
    "glob",
    "grep",
    "write_file",
    "edit_file",
    "execute",
)
"""The console's tools, as the library names them; the model sees them prefixed."""

TERMINAL_TOOL_INFOS: tuple[CapabilityToolInfo, ...] = tuple(
    CapabilityToolInfo(id=f"{PREFIX}_{tool}", description=TOOL_TEXT[tool].summary)
    for tool in TERMINAL_TOOLS
)
"""Every tool the terminal offers, with the library's own summary as its text.

None is side-effecting. A write is approved per **mount** - the author marks a
writable folder "ask first", and Mirage asks about a line that writes there - so
gating a tool would ask about `mirage_execute ls` as much as about `rm`. A binding
that wants a tool gated anyway still gets it with a `tool_approval` override.
"""

MountValue = str | int | float | bool | SecretStr | list[str] | None
"""What a resolved mount's config holds: an author's option, or an unsealed secret."""


@dataclass(frozen=True)
class ResolvedMount:
    """One folder of the terminal, as the runner built it for this run."""

    path: str
    """Where it appears, e.g. `/drive/` - absolute, with a trailing slash."""
    backend: str
    """Mirage's registry name for it, e.g. `gdrive`."""
    mode: Literal["read", "write"]
    approve_writes: bool
    config: Mapping[str, MountValue] = field(repr=False)
    """The backend's config, secrets as `SecretStr`, and out of the repr altogether."""
    title: str
    """What the folder is, in the model's instructions: `Google Drive of ana@acme.com`."""

    def build(self) -> Mount:
        """The Mirage mount for this folder. Opens no connection: backends start lazily."""
        from mirage import MountMode
        from mirage.vfs.registry import build_vfs
        from mirage.workspace.mount.spec import Mount

        vfs = build_vfs(self.backend, None if self.backend == "ram" else dict(self.config))
        return Mount(vfs, mode=MountMode.WRITE if self.mode == "write" else MountMode.READ)


@dataclass(frozen=True)
class ResolvedTerminal:
    """What the runner leaves under `MIRAGE_MOUNTS_RESOURCE` for one run."""

    mounts: tuple[ResolvedMount, ...]
    notes: tuple[str, ...] = ()
    """One sentence per folder left out, for the model's instructions."""
