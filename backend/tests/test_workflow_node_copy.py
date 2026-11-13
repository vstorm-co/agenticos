"""The console names every workflow step in the reader's language, from the registry's words.

The registry writes a step's name, description and port labels in English, and the
console's `workflowNodes` catalog holds the same copy per locale. A step added here
with no entry there reads in English in a Polish palette; one renamed here keeps its
old name on the canvas while the API, the Architect and the docs use the new one.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.workflows._registry import all_node_definitions

MESSAGES_PATH = Path(__file__).resolve().parents[2] / "frontend" / "messages"
LOCALES = ("en", "pl", "de", "tr")


def _key(text: str) -> str:
    """The catalog key the console reads: `nodeCopyKey` in `lib/workflows/node-copy.ts`."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


# `agent.run` picks its agent, or holds one inline, in a control of its own: the
# agent spec's fields inside it are the Builder's to word, not the step form's.
UNWORDED_NESTING = {"agent.run"}
_COPY_KEYS = (
    ("title", "title"),
    ("description", "description"),
    ("x-placeholder", "placeholder"),
    ("x-hint", "hint"),
)


def _icu(text: str) -> str:
    """`text` as a message: a brace quoted, so `{Price}` reads as written, not as an argument."""
    return re.sub(r"[{}]", lambda brace: f"'{brace.group(0)}'", text)


def _fields(schema: dict[str, Any], *, nested: bool) -> dict[str, dict[str, str]]:
    """Each field's copy by its path - `localizeSchema` in the console walks the same way."""
    defs = schema.get("$defs", {})
    found: dict[str, dict[str, str]] = {}
    seen: set[str] = set()

    def through(ref: object, path: list[str]) -> None:
        if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
            return
        name = ref.removeprefix("#/$defs/")
        if name in seen or name not in defs:
            return
        seen.add(name)
        walk(defs[name], path)

    def walk(target: dict[str, Any], path: list[str]) -> None:
        for name, prop in (target.get("properties") or {}).items():
            at = [*path, name]
            copy = {key: _icu(prop[src]) for src, key in _COPY_KEYS if src in prop}
            # A code field's example is code: the same in every language, so not copy.
            if "x-code" in prop:
                copy.pop("placeholder", None)
            if copy:
                found["__".join(at)] = copy
            if not nested:
                continue
            through(prop.get("$ref"), at)
            if "properties" in prop:
                walk(prop, at)
            items(prop, at)
            for branch in prop.get("anyOf", []):
                through(branch.get("$ref"), at)
                items(branch, at)

    def items(schema: dict[str, Any], path: list[str]) -> None:
        item = schema.get("items")
        if not isinstance(item, dict):
            return
        at = [*path, "items"]
        through(item.get("$ref"), at)
        if "properties" in item:
            walk(item, at)

    walk(schema, [])
    return found


def _registry_fields() -> dict[str, dict[str, dict[str, dict[str, str]]]]:
    worded: dict[str, dict[str, dict[str, dict[str, str]]]] = {}
    for d in all_node_definitions():
        for kind, model in (("config", d.config_schema), ("input", d.input_schema)):
            if model is None:
                continue
            fields = _fields(model.model_json_schema(), nested=d.id not in UNWORDED_NESTING)
            if fields:
                worded.setdefault(_key(d.id), {})[kind] = fields
    return worded


def _copy(locale: str) -> dict[str, dict[str, object]]:
    catalog = json.loads((MESSAGES_PATH / f"{locale}.json").read_text(encoding="utf-8"))
    return catalog["workflowNodes"]


def test_ids_and_labels_never_collide_as_keys():
    definitions = all_node_definitions()
    assert len({_key(d.id) for d in definitions}) == len(definitions)
    labels = {port.label for d in definitions for port in d.ports}
    assert len({_key(label) for label in labels}) == len(labels)


def _strings(tree: object) -> list[str]:
    if isinstance(tree, dict):
        return [text for value in tree.values() for text in _strings(value)]
    return [tree] if isinstance(tree, str) else []


@pytest.mark.parametrize("locale", LOCALES)
def test_no_copy_holds_what_a_message_would_parse(locale: str):
    """A brace is an ICU argument and `<` opens a tag: copy holding either renders
    broken, or throws, though the English still equals the registry's."""
    unquoted = [text.replace("'{'", "").replace("'}'", "") for text in _strings(_copy(locale))]
    assert [text for text in unquoted if re.search(r"[{}<]", text)] == []


def test_the_english_copy_is_the_registry_s():
    copy = _copy("en")

    assert copy["node"] == {
        _key(d.id): {"name": d.name, "description": d.description} for d in all_node_definitions()
    }
    labels = {port.label for d in all_node_definitions() for port in d.ports}
    assert copy["port"] == {_key(label): label for label in labels}


@pytest.mark.parametrize("locale", LOCALES[1:])
def test_every_locale_names_every_step_and_port_and_nothing_else(locale: str):
    english, translated = _copy("en"), _copy(locale)

    assert set(translated) == {"node", "port", "field"}
    assert translated["node"].keys() == english["node"].keys()
    for key, entry in translated["node"].items():
        assert isinstance(entry, dict) and entry.keys() == {"name", "description"}, key
        assert all(isinstance(text, str) and text.strip() for text in entry.values()), key
    assert translated["port"].keys() == english["port"].keys()


def test_the_english_field_copy_is_the_registry_s():
    assert _copy("en")["field"] == _registry_fields()


@pytest.mark.parametrize("locale", LOCALES[1:])
def test_every_locale_words_every_field_it_is_given(locale: str):
    english, translated = _copy("en")["field"], _copy(locale)["field"]

    def shape(tree: object) -> object:
        if isinstance(tree, dict):
            return {key: shape(value) for key, value in tree.items()}
        assert isinstance(tree, str) and tree.strip(), tree
        return None

    assert shape(translated) == shape(english)
