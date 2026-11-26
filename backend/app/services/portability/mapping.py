"""Explicit reference remapping without rewriting UUID-shaped application data."""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from pydantic import JsonValue

from app.core.exceptions import BadRequestError
from app.core.field_errors import refused_field
from app.schemas.resource_bundle import BundleDestination, BundlePath, BundleResource


class _Removed:
    pass


_REMOVED = _Removed()


@dataclass(frozen=True, slots=True)
class ReboundDefinition:
    definition: dict[str, JsonValue]
    skipped: tuple[BundlePath, ...]


def _refuse(message: str) -> BadRequestError:
    return refused_field("bundle", message)


def _at(definition: dict[str, JsonValue], path: BundlePath) -> JsonValue:
    current: JsonValue = definition
    for part in path:
        if isinstance(current, dict) and isinstance(part, str) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and isinstance(part, int) and 0 <= part < len(current):
            current = current[part]
            continue
        raise _refuse("A declared reference path is not present in its definition")
    return current


def rebind_definition(
    resource: BundleResource,
    destinations: Mapping[str, UUID | BundleDestination | None],
    *,
    omit: Mapping[BundlePath, BundlePath] | None = None,
) -> ReboundDefinition:
    """Apply an authorized destination map to schema-verified reference paths.

    The domain adapter must verify manifest paths against its owned schema and
    check destination authority before calling. `omit` identifies a containing
    binding to remove when its required reference is skipped, such as one MCP
    server. It is derived by the adapter, never accepted directly from an upload.
    """
    if resource.definition is None:
        raise _refuse("A reference-only resource has no definition to import")
    replacements: dict[BundlePath, str | int] = {}
    key_replacements: dict[BundlePath, str] = {}
    removals: set[BundlePath] = set()
    skipped: list[BundlePath] = []
    containers = {} if omit is None else omit
    known_paths = {reference.path for reference in resource.references}
    if not set(containers).issubset(known_paths):
        raise _refuse("Omission rules must describe declared references")
    for reference in resource.references:
        if reference.target not in destinations:
            raise _refuse("Choose a destination or explicitly skip every referenced resource")
        current = (
            _at(resource.definition, reference.path[:-1])
            if reference.is_key
            else _at(resource.definition, reference.path)
        )
        if reference.is_key:
            name = reference.path[-1]
            if not isinstance(current, dict) or not isinstance(name, str) or name not in current:
                raise _refuse("A dictionary reference must name an existing object key")
        elif reference.destination_field == "version_number":
            if type(current) is not int:
                raise _refuse("A version reference must contain a version number")
        elif not isinstance(current, str):
            raise _refuse("A resource reference must identify one resource")
        destination = destinations[reference.target]
        if destination is not None:
            if reference.destination_field == "version_number":
                if (
                    not isinstance(destination, BundleDestination)
                    or destination.version_number is None
                ):
                    raise _refuse("Resolve the destination version before importing this binding")
                replacements[reference.path] = destination.version_number
            else:
                identity = (
                    destination.id if isinstance(destination, BundleDestination) else destination
                )
                if reference.is_key:
                    key_replacements[reference.path] = str(identity)
                else:
                    replacements[reference.path] = str(identity)
            continue
        container = containers.get(reference.path, reference.path)
        if not container or reference.path[: len(container)] != container:
            raise _refuse("A skipped binding must contain its declared reference")
        removals.add(container)
        skipped.append(reference.path)

    def rewrite(value: JsonValue, path: BundlePath) -> JsonValue | _Removed:
        if path in removals:
            return _REMOVED
        if path in replacements:
            return replacements[path]
        if isinstance(value, dict):
            result: dict[str, JsonValue] = {}
            for key, item in value.items():
                rewritten = rewrite(item, (*path, key))
                if not isinstance(rewritten, _Removed):
                    destination_key = key_replacements.get((*path, key), key)
                    if destination_key in result:
                        raise _refuse(
                            "Two references cannot overwrite the same destination configuration key"
                        )
                    result[destination_key] = rewritten
            return result
        if isinstance(value, list):
            items: list[JsonValue] = []
            for index, item in enumerate(value):
                rewritten = rewrite(item, (*path, index))
                if not isinstance(rewritten, _Removed):
                    items.append(rewritten)
            return items
        return value

    definition: dict[str, JsonValue] = {}
    for key, item in resource.definition.items():
        rewritten = rewrite(item, (key,))
        if not isinstance(rewritten, _Removed):
            destination_key = key_replacements.get((key,), key)
            if destination_key in definition:
                raise _refuse(
                    "Two references cannot overwrite the same destination configuration key"
                )
            definition[destination_key] = rewritten
    return ReboundDefinition(definition=definition, skipped=tuple(skipped))
