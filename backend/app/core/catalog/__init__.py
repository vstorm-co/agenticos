"""Deployment catalogs as data files, in one directory.

The MCP servers an organization can connect and the services a secret can be
for used to be Python literals inside the modules that consume them. The lists
themselves are pure data - adding an entry never needs code - so they live here
as JSON, one file per catalog, beside the custom brand icons a deployment may
add. What *interprets* an entry (the resolver that builds a model client, the
service that connects a server) stays in code, which is why the model provider
table is deliberately not here: a provider entry without its client-building
branch would be a lie about what the deployment can reach.

Every file is validated with the consuming module's own types the moment it is
loaded, at import time. A malformed entry is a refusal to start, not a server
that silently vanishes from the picker.

Custom icons: any `icons/<name>.svg` is served by `GET /catalog/icons` and
drawn by the frontend for a catalog entry or provider whose id matches and
which no compiled-in icon set carries. The file's own colours are ignored - it
is rendered as a `currentColor` silhouette, so the console's monochrome
register holds by construction. `icons/README.md` states the contract.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import TypeAdapter

_DIR = Path(__file__).parent

ICONS_DIR = _DIR / "icons"


def load[T](filename: str, adapter: TypeAdapter[T]) -> T:
    """Parse and validate one catalog file, loudly.

    Raises:
        pydantic.ValidationError: If any entry does not fit the consuming
            module's type. Deliberately not caught anywhere: this runs at
            import, so a bad file stops the deployment instead of shipping a
            catalog with a hole in it.
    """
    return adapter.validate_json((_DIR / filename).read_bytes())


# Also the whole traversal defence: a name that cannot contain a dot or a slash
# cannot name a path outside ICONS_DIR.
_ICON_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def custom_icon_names() -> list[str]:
    """The custom marks this deployment ships, sorted for a stable response."""
    return sorted(p.stem for p in ICONS_DIR.glob("*.svg") if _ICON_NAME.fullmatch(p.stem))


def custom_icon(name: str) -> Path | None:
    """The file for one custom mark, or None for a name not served.

    None covers both absences - a name outside the slug grammar and a file that
    does not exist - because the route answers 404 to each; distinguishing them
    would only describe the filesystem to whoever is probing it.
    """
    if not _ICON_NAME.fullmatch(name):
        return None
    path = ICONS_DIR / f"{name}.svg"
    return path if path.is_file() else None
