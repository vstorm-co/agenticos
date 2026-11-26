"""Text assets retain exact bytes and cannot target arbitrary definition fields."""

from pathlib import Path

import pytest
from pydantic import JsonValue

from app.core.exceptions import BadRequestError
from app.schemas.resource_bundle import (
    BundleAsset,
    BundleContentLayer,
    BundleResource,
    BundleResourceKind,
    ResourceBundle,
)
from app.services.portability import file_bundle


def _bundle(kind: str, definition: dict[str, JsonValue] | None) -> ResourceBundle:
    resource = BundleResource(
        key=f"{kind}/root",
        kind=BundleResourceKind(kind),
        name="Resource",
        definition=definition,
        included=frozenset({BundleContentLayer.DEFINITION})
        if definition is not None
        else frozenset(),
    )
    return ResourceBundle(roots=(resource.key,), resources=(resource,))


@pytest.mark.parametrize("kind", ["context", "skill", "skill_version", "skill_fork"])
def test_exact_text_roundtrip_deduplicates_asset_content(tmp_path: Path, kind: str) -> None:
    text = "  Exact\r\nUnicode: αβ\r\n"
    definition: dict[str, JsonValue] = (
        {"name": "Resource", "content": text}
        if kind == "context"
        else {
            "name": "Resource",
            "files": [
                {"name": "references/one.txt", "content": text},
                {"name": "two.txt", "content": text},
            ],
        }
    )
    original = _bundle(kind, definition)
    staged, files = file_bundle.externalize_text(original, tmp_path)
    assert len(files) == 1
    assert len(staged.assets) == (1 if kind == "context" else 2)
    assert staged.assets[0].sha256 in files
    assert file_bundle.hydrate_text(staged, files).resources[0].definition == definition
    assert original.resources[0].definition == definition


@pytest.mark.parametrize(
    "kind,definition",
    [
        ("agent", {"name": "Agent"}),
        ("context", None),
        ("context", {"content": 1}),
        ("skill", {"files": []}),
        ("skill", {"files": None}),
    ],
)
def test_resources_without_text_assets_remain_unchanged(
    tmp_path: Path, kind: str, definition: dict[str, JsonValue] | None
) -> None:
    original = _bundle(kind, definition)
    staged, files = file_bundle.externalize_text(original, tmp_path)
    assert staged == original and files == {}
    assert file_bundle.hydrate_text(staged, files) == staged


@pytest.mark.parametrize(
    "entry", [None, {"name": 4, "content": "text"}, {"name": "file", "content": False}]
)
def test_invalid_skill_file_is_refused_before_staging(tmp_path: Path, entry: JsonValue) -> None:
    with pytest.raises(BadRequestError, match="skill file"):
        file_bundle.externalize_text(_bundle("skill", {"files": [entry]}), tmp_path)


def test_oversized_text_is_refused_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(file_bundle, "MAX_TEXT_ASSET_BYTES", 2)
    with pytest.raises(BadRequestError, match="16 MiB"):
        file_bundle.externalize_text(_bundle("context", {"content": "large"}), tmp_path)
    assert not list(tmp_path.iterdir())


def _asset_bundle(
    tmp_path: Path,
    kind: str,
    definition: dict[str, JsonValue] | None,
    *,
    name: str = "content",
    layer: BundleContentLayer = BundleContentLayer.CONTEXT_CONTENT,
    body: bytes = b"text",
) -> tuple[ResourceBundle, dict[str, Path]]:
    import hashlib

    digest = hashlib.sha256(body).hexdigest()
    path = tmp_path / digest
    path.write_bytes(body)
    bundle = _bundle(kind, definition)
    resource = bundle.resources[0].model_copy(
        update={"included": frozenset({BundleContentLayer.DEFINITION, layer})}
    )
    asset = BundleAsset(
        resource=resource.key,
        layer=layer,
        name=name,
        sha256=digest,
        size_bytes=len(body),
        media_type="text/plain",
    )
    return bundle.model_copy(update={"resources": (resource,), "assets": (asset,)}), {digest: path}


@pytest.mark.parametrize(
    "kind,layer,name",
    [
        ("agent", BundleContentLayer.CONTEXT_CONTENT, "content"),
        ("context", BundleContentLayer.CONTEXT_CONTENT, "other"),
        ("skill", BundleContentLayer.CONTEXT_CONTENT, "content"),
    ],
)
def test_asset_locations_are_owned_by_the_resource_schema(
    tmp_path: Path, kind: str, layer: BundleContentLayer, name: str
) -> None:
    bundle, files = _asset_bundle(tmp_path, kind, {"content": ""}, layer=layer, name=name)
    with pytest.raises(BadRequestError, match="supported text"):
        file_bundle.hydrate_text(bundle, files)


def test_hydration_refuses_oversized_or_non_utf8_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, files = _asset_bundle(tmp_path, "context", {"content": ""}, body=b"\xff")
    with pytest.raises(BadRequestError, match="UTF-8"):
        file_bundle.hydrate_text(bundle, files)
    monkeypatch.setattr(file_bundle, "MAX_TEXT_ASSET_BYTES", 0)
    with pytest.raises(BadRequestError, match="supported text"):
        file_bundle.hydrate_text(bundle, files)


@pytest.mark.parametrize("definition", [None, {"content": "not a placeholder"}])
def test_context_assets_need_an_included_empty_placeholder(
    tmp_path: Path, definition: dict[str, JsonValue] | None
) -> None:
    bundle, files = _asset_bundle(tmp_path, "context", definition)
    with pytest.raises(BadRequestError, match=r"definition|placeholder"):
        file_bundle.hydrate_text(bundle, files)


@pytest.mark.parametrize(
    "definition",
    [
        {"files": None},
        {"files": [False]},
        {"files": [{"name": 1}]},
        {"files": [{"name": "file", "content": "not empty"}]},
        {"files": [{"name": "file", "content": ""}, {"name": "file", "content": ""}]},
        {"files": [{"name": "other", "content": ""}]},
    ],
)
def test_skill_assets_need_one_exact_file_placeholder(
    tmp_path: Path, definition: dict[str, JsonValue]
) -> None:
    bundle, files = _asset_bundle(
        tmp_path, "skill", definition, name="file", layer=BundleContentLayer.SKILL_FILES
    )
    with pytest.raises(BadRequestError):
        file_bundle.hydrate_text(bundle, files)


def test_inline_skill_files_survive_when_other_files_are_assets(tmp_path: Path) -> None:
    bundle, files = _asset_bundle(
        tmp_path,
        "skill",
        {"files": [{"name": "inline", "content": "original"}, {"name": "file", "content": ""}]},
        name="file",
        layer=BundleContentLayer.SKILL_FILES,
    )
    assert (
        file_bundle.hydrate_text(bundle, files).resources[0].definition["files"][0]["content"]
        == "original"
    )


def test_zip_staging_deduplicates_shared_text_bytes(tmp_path: Path) -> None:
    from app.services.portability.archive import write_bundle
    from app.services.portability.transfers import _read_zip

    agent = _bundle("agent", {"name": "Agent"})
    contexts = tuple(
        BundleResource(
            key=f"context/{number}",
            kind=BundleResourceKind.CONTEXT,
            name="Context",
            definition={"name": "Context", "content": "shared"},
            included=frozenset({BundleContentLayer.DEFINITION}),
        )
        for number in range(2)
    )
    bundle = agent.model_copy(update={"resources": (*agent.resources, *contexts)})
    staged, files = file_bundle.externalize_text(bundle, tmp_path)
    archive = tmp_path / "bundle.zip"
    with archive.open("w+b") as target:
        write_bundle(target, staged, files)
    extracted = tmp_path / "verified"
    extracted.mkdir()
    manifest, verified = _read_zip(archive, extracted)
    assert manifest == staged and len(verified) == 1
