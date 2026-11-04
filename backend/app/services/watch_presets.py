"""Ready-made watches for the servers in the MCP catalog (#2301).

A person connecting their GitHub is offered "pull requests waiting on my
review" rather than an empty box asking what to watch. Each preset is what the
model is told to look for, and how often by default; what the card calls it is
the console's to translate, by `key`. A server with no preset - and any server
outside the catalog - is still watchable, in the person's own words.

Data, like the catalog it extends: `catalog.load` validates every entry at
import, and `test_watch_presets` holds each `catalog_key` to a real entry.
"""

from dataclasses import dataclass

from pydantic import TypeAdapter

from app.core import catalog


@dataclass(frozen=True)
class WatchPreset:
    key: str
    catalog_key: str
    instructions: str
    interval_minutes: int
    urgent: bool = False


PRESETS: tuple[WatchPreset, ...] = catalog.load(
    "watch_presets.json", TypeAdapter(tuple[WatchPreset, ...])
)

BY_KEY: dict[str, WatchPreset] = {preset.key: preset for preset in PRESETS}


def for_server(catalog_key: str | None) -> tuple[WatchPreset, ...]:
    """The presets offered for one catalog server, in catalog order; none for a custom one."""
    return tuple(preset for preset in PRESETS if preset.catalog_key == catalog_key)
