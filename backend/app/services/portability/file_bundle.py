"""Content-addressed text assets keep large skill files out of the JSON manifest."""

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

from pydantic import JsonValue

from app.core.exceptions import BadRequestError
from app.schemas.resource_bundle import (
    BundleAsset,
    BundleContentLayer,
    BundleResourceKind,
    ResourceBundle,
)

MAX_TEXT_ASSET_BYTES = 16 * 1024 * 1024


def externalize_text(
    bundle: ResourceBundle, directory: Path
) -> tuple[ResourceBundle, dict[str, Path]]:
    """Move exact text bodies to files under a caller-owned temporary directory.

    The manifest retains validated, empty placeholders; hydration only replaces
    those placeholders after every archive member has passed its digest check.
    """
    resources = []
    assets: list[BundleAsset] = []
    files: dict[str, Path] = {}
    for resource in bundle.resources:
        definition = resource.definition
        if definition is None:
            resources.append(resource)
            continue
        definition = dict(definition)
        layer: BundleContentLayer | None = None
        if resource.kind == BundleResourceKind.CONTEXT:
            content = definition.get("content")
            if isinstance(content, str):
                asset = _stage(
                    resource.key,
                    BundleContentLayer.CONTEXT_CONTENT,
                    "content",
                    content,
                    directory,
                    files,
                )
                assets.append(asset)
                definition["content"] = ""
                layer = asset.layer
        elif resource.kind in (
            BundleResourceKind.SKILL,
            BundleResourceKind.SKILL_VERSION,
            BundleResourceKind.SKILL_FORK,
        ):
            entries = definition.get("files")
            if isinstance(entries, list):
                rewritten: list[JsonValue] = []
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise BadRequestError(
                            message="A skill file does not match its portable definition"
                        )
                    name, content = entry.get("name"), entry.get("content")
                    if not isinstance(name, str) or not isinstance(content, str):
                        raise BadRequestError(
                            message="A skill file does not match its portable definition"
                        )
                    assets.append(
                        _stage(
                            resource.key,
                            BundleContentLayer.SKILL_FILES,
                            name,
                            content,
                            directory,
                            files,
                        )
                    )
                    rewritten.append({**entry, "content": ""})
                definition["files"] = rewritten
                if entries:
                    layer = BundleContentLayer.SKILL_FILES
        resources.append(
            resource.model_copy(
                update={
                    "definition": definition,
                    "included": resource.included | ({layer} if layer is not None else set()),
                }
            )
        )
    return bundle.model_copy(update={"resources": tuple(resources), "assets": tuple(assets)}), files


def _stage(
    resource: str,
    layer: BundleContentLayer,
    name: str,
    content: str,
    directory: Path,
    files: dict[str, Path],
) -> BundleAsset:
    data = content.encode("utf-8")
    if len(data) > MAX_TEXT_ASSET_BYTES:
        raise BadRequestError(message="A text resource exceeds the 16 MiB transfer limit")
    digest = sha256(data).hexdigest()
    path = directory / digest
    if digest not in files:
        path.write_bytes(data)
        files[digest] = path
    return BundleAsset(
        resource=resource,
        layer=layer,
        name=name,
        sha256=digest,
        size_bytes=len(data),
        media_type="text/plain; charset=utf-8",
    )


def hydrate_text(bundle: ResourceBundle, files: Mapping[str, Path]) -> ResourceBundle:
    """Accept only declared text locations, without interpreting filenames as paths."""
    by_key = {resource.key: resource for resource in bundle.resources}
    replacements: dict[str, dict[str, str]] = {}
    for asset in bundle.assets:
        resource = by_key[asset.resource]
        valid_context = (
            resource.kind == BundleResourceKind.CONTEXT
            and asset.layer == BundleContentLayer.CONTEXT_CONTENT
            and asset.name == "content"
        )
        valid_skill = (
            resource.kind
            in (
                BundleResourceKind.SKILL,
                BundleResourceKind.SKILL_VERSION,
                BundleResourceKind.SKILL_FORK,
            )
            and asset.layer == BundleContentLayer.SKILL_FILES
        )
        if not (valid_context or valid_skill) or asset.size_bytes > MAX_TEXT_ASSET_BYTES:
            raise BadRequestError(message="This asset does not identify a supported text resource")
        try:
            text = files[asset.sha256].read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BadRequestError(message="A text asset must use UTF-8") from exc
        replacements.setdefault(asset.resource, {})[asset.name] = text
    resources = []
    for resource in bundle.resources:
        values = replacements.get(resource.key)
        if values is None:
            resources.append(resource)
            continue
        if resource.definition is None:
            raise BadRequestError(message="An asset requires an included resource definition")
        definition = dict(resource.definition)
        if resource.kind == BundleResourceKind.CONTEXT:
            if definition.get("content") != "":
                raise BadRequestError(
                    message="A text asset must replace an empty content placeholder"
                )
            definition["content"] = values["content"]
        else:
            entries = definition.get("files")
            if not isinstance(entries, list):
                raise BadRequestError(message="A skill asset requires a declared file")
            rewritten: list[JsonValue] = []
            used: set[str] = set()
            for entry in entries:
                if not isinstance(entry, dict):
                    raise BadRequestError(message="A skill asset requires a declared filename")
                name = entry.get("name")
                if not isinstance(name, str):
                    raise BadRequestError(message="A skill asset requires a declared filename")
                if name in values:
                    if entry.get("content") != "" or name in used:
                        raise BadRequestError(
                            message="A skill asset must replace one empty file placeholder"
                        )
                    entry = {**entry, "content": values[name]}
                    used.add(name)
                rewritten.append(entry)
            if used != values.keys():
                raise BadRequestError(message="A skill asset does not identify a declared file")
            definition["files"] = rewritten
        resources.append(resource.model_copy(update={"definition": definition}))
    return bundle.model_copy(update={"resources": tuple(resources), "assets": ()})
