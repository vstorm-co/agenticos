"""Write the runtime allowlist the compose files hand to `sandboxd`.

`SANDBOXD_RUNTIMES` was hand-written JSON in three compose files, describing the
same runtimes the connection dialog offers - so adding a package meant editing
four places and remembering, in three of them, that `network_mode` is not
inherited from anywhere. It is generated from
`app/core/catalog/sandbox_runtimes.json` now, and
`tests/test_sandbox_runtime_catalog.py` fails when a file has drifted from it.

Generated *into* the compose files rather than read from a side file at start-up,
deliberately. `env_file` would keep the value out of a tracked file, and a
deployment that ran `docker compose up` without generating it first would get the
library's own three-runtime default with nothing said - which is the class of
silent failure this catalogue exists to remove.
"""

from __future__ import annotations

import re
from pathlib import Path

import click

from app.commands import command, error, info, success
from app.services.sandbox_runtimes import CATALOG, allowlist_value

COMPOSE_FILES = ("docker-compose.yml", "docker-compose-dev.yml", "docker-compose-prod.yml")
"""Every file that starts a `sandboxd`. Local, the dev server, production."""

_KEY = "SANDBOXD_RUNTIMES"
_INDENT = " " * 6

_BLOCK = re.compile(
    rf"^{_INDENT}{_KEY}:.*?(?=^{_INDENT}(?:[A-Za-z_]|#)|^ {{4}}[a-z])",
    re.MULTILINE | re.DOTALL,
)
"""The key and every continuation line of its value.

Anchored on the *next* key at the same indent, or on the next block of the
service, because a folded YAML scalar has no terminator of its own.

**A comment ends it too**, and the `#` is the whole reason this pattern is worth
a docstring: without it, a run consumed every commented line between this key and
the next one and wrote them out of the file. Six lines explaining
`SANDBOXD_SANDBOX_UID` went that way, in all three files, in one command - and a
generator that silently deletes the prose beside what it generates is worse than
one that refuses.
"""

_NETWORK_MODE = re.compile(rf"^{_INDENT}SANDBOXD_NETWORK_MODE:\s*(\S+)", re.MULTILINE)


def _repo_root() -> Path:
    """The directory holding the compose files, from this file's own location."""
    return Path(__file__).resolve().parents[3]


def _rendered(text: str) -> str:
    """The line this file should carry, for the network default it sets.

    Read from the file rather than assumed: a deployment that ran its sandboxes
    on `bridge` service-wide would otherwise be given a `network_mode` on every
    entry that needs one, which is true but says the opposite of what the
    service-wide setting already says.
    """
    found = _NETWORK_MODE.search(text)
    mode = "bridge" if found is not None and found.group(1) == "bridge" else "none"
    # Single-quoted, because a YAML plain scalar may not open with `{` and the
    # JSON itself holds no single quote to escape.
    return f"{_INDENT}{_KEY}: '{allowlist_value(network_mode=mode)}'\n"


@command("sandbox-runtimes", help="Write the runtime allowlist into the compose files")
@click.option("--write", is_flag=True, help="Rewrite the files rather than printing the value")
def sandbox_runtimes(write: bool) -> None:
    """Print the allowlist, or write it into every compose file that starts one."""
    if not write:
        click.echo(allowlist_value())
        info(f"{len(CATALOG)} runtime(s) from app/core/catalog/sandbox_runtimes.json")
        return

    root = _repo_root()
    changed = 0
    for name in COMPOSE_FILES:
        path = root / name
        text = path.read_text()
        if _BLOCK.search(text) is None:
            error(f"{name} has no {_KEY} block to replace")
            raise SystemExit(1)
        updated = _BLOCK.sub(_rendered(text), text, count=1)
        if updated != text:
            path.write_text(updated)
            changed += 1
            info(f"{name} updated")
    success(f"{len(CATALOG)} runtime(s) written to {changed} of {len(COMPOSE_FILES)} file(s)")
