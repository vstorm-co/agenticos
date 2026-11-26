"""Bounded data documents shared by file downloads and import previews."""

import json
from typing import Literal

import yaml
from pydantic import ConfigDict, JsonValue, TypeAdapter, ValidationError

from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.core.field_errors import field_problems
from app.schemas.resource_bundle import BundleContentLayer, BundleSelection, ResourceBundle
from app.services.portability.snapshots import agent_snapshot

MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_DOCUMENT_EVENTS = 100_000
_JSON_DATA = TypeAdapter(JsonValue, config=ConfigDict(allow_inf_nan=False))


def parse_document(text: str) -> ResourceBundle:
    """Read a manifest or legacy agent YAML/JSON without resolving external content.

    YAML aliases are deliberately refused: a small file must not expand into an
    unbounded graph, including recursive structures. Input diagnostics contain
    field paths, never the submitted instructions or credential references.
    """
    if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise BadRequestError(message="Configuration files must not exceed 4 MiB; use a ZIP bundle")
    try:
        for count, event in enumerate(yaml.parse(text, Loader=yaml.SafeLoader)):
            if count >= MAX_DOCUMENT_EVENTS or isinstance(event, yaml.events.AliasEvent):
                raise BadRequestError(
                    message="Configuration files must not contain YAML aliases or excessive nesting"
                )
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        pending = [] if node is None else [node]
        while pending:
            current = pending.pop()
            if isinstance(current, yaml.nodes.MappingNode):
                keys: set[str] = set()
                for key, value in current.value:
                    if (
                        not isinstance(key, yaml.nodes.ScalarNode)
                        or key.tag != "tag:yaml.org,2002:str"
                        or key.value in keys
                    ):
                        raise BadRequestError(
                            message="Configuration objects require unique string keys"
                        )
                    keys.add(key.value)
                    pending.append(value)
            elif isinstance(current, yaml.nodes.SequenceNode):
                pending.extend(current.value)
        data = yaml.safe_load(text)
    except (yaml.YAMLError, RecursionError) as exc:
        raise BadRequestError(message="The file is not a valid YAML or JSON configuration") from exc
    try:
        data = _JSON_DATA.validate_python(data)
        if isinstance(data, dict) and data.get("format") == "agenticos.bundle":
            return ResourceBundle.model_validate(data)
        return agent_snapshot(AgentSpec.model_validate(data))
    except ValidationError as exc:
        raise BadRequestError(
            message="The file does not match the AgenticOS configuration format",
            details={
                "fields": field_problems(
                    exc.errors(include_input=False, include_url=False), root="file"
                )
            },
        ) from exc


def select_content(bundle: ResourceBundle, selection: BundleSelection) -> ResourceBundle:
    """Keep the dependency graph while removing content the user did not select."""
    by_key = {item.key: item for item in bundle.resources}
    if not set(selection.resources).issubset(by_key):
        raise BadRequestError(message="The selection names a resource outside this export")
    chosen = {item.key: selection.resources.get(item.key, frozenset()) for item in bundle.resources}
    for root in bundle.roots:
        if BundleContentLayer.DEFINITION not in chosen[root]:
            raise BadRequestError(message="An export must include its root definition")
    for key, layers in chosen.items():
        if not layers.issubset(by_key[key].included):
            raise BadRequestError(message="The selected content is not available in this export")
        if layers and BundleContentLayer.DEFINITION not in layers:
            raise BadRequestError(
                message="Select a resource's definition before including its content"
            )
    return bundle.model_copy(
        update={
            "resources": tuple(
                item.model_copy(
                    update={
                        "included": chosen[item.key],
                        "definition": item.definition if chosen[item.key] else None,
                        "references": item.references if chosen[item.key] else (),
                    }
                )
                for item in bundle.resources
            ),
            "assets": tuple(item for item in bundle.assets if item.layer in chosen[item.resource]),
        }
    )


def document_bytes(bundle: ResourceBundle, file_format: Literal["yaml", "json"]) -> bytes:
    """Serialize textual content only; binary assets require the ZIP representation."""
    if bundle.assets:
        raise BadRequestError(message="This export includes files; download it as a ZIP bundle")
    data = bundle.model_dump(mode="json")
    encoded = (
        (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if file_format == "json"
        else yaml.safe_dump(data, sort_keys=False, allow_unicode=True).encode("utf-8")
    )
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise BadRequestError(message="This configuration exceeds 4 MiB; use a ZIP bundle")
    return encoded
