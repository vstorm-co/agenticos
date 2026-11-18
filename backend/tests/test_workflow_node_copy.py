"""The console names every workflow step from the registry's words.

The registry writes a step's name, description and port labels in English, and the
console's `workflowNodes` catalog holds the same copy. The T3 fork ships English only
(#161). A step renamed here keeps its old name on the canvas while the API, the
Architect and the docs use the new one.
"""

import json
import re
from pathlib import Path

from app.workflows._registry import all_node_definitions

MESSAGES_PATH = Path(__file__).resolve().parents[2] / "frontend" / "messages"


def _key(text: str) -> str:
    """The catalog key the console reads: `nodeCopyKey` in `lib/workflows/node-copy.ts`."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _copy(locale: str) -> dict[str, dict[str, object]]:
    catalog = json.loads((MESSAGES_PATH / f"{locale}.json").read_text(encoding="utf-8"))
    return catalog["workflowNodes"]


def test_ids_and_labels_never_collide_as_keys():
    definitions = all_node_definitions()
    assert len({_key(d.id) for d in definitions}) == len(definitions)


def test_the_english_copy_is_the_registry_s():
    copy = _copy("en")

    assert copy["node"] == {
        _key(d.id): {"name": d.name, "description": d.description} for d in all_node_definitions()
    }
    labels = {port.label for d in all_node_definitions() for port in d.ports}
    assert copy["port"] == {_key(label): label for label in labels}
