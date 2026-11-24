"""Bundle files are data, with bounded, verified content and explicit references."""

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from stat import S_IFLNK
from uuid import uuid4
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

import pytest
from pydantic import ValidationError

from app.core.exceptions import BadRequestError
from app.schemas.resource_bundle import (
    BundleAsset,
    BundleContentLayer,
    BundleReference,
    BundleResource,
    BundleResourceKind,
    ResourceBundle,
)
from app.services.portability import BundleLimits, open_bundle


def _asset(content: bytes = b"# Instructions\n") -> BundleAsset:
    return BundleAsset(
        resource="skill/one",
        layer=BundleContentLayer.SKILL_FILES,
        name="references/guide.md",
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
        media_type="text/markdown",
    )


def _manifest(asset: BundleAsset | None = None) -> ResourceBundle:
    return ResourceBundle(
        roots=("agent/one",),
        resources=(
            BundleResource(
                key="agent/one",
                kind=BundleResourceKind.AGENT,
                name="Researcher",
                source_id=uuid4(),
                definition={
                    "skill_ids": ["source-id"],
                    "instructions": "A UUID in text stays text.",
                },
                references=(BundleReference(path=("skill_ids", 0), target="skill/one"),),
                included=frozenset({BundleContentLayer.DEFINITION}),
            ),
            BundleResource(
                key="skill/one",
                kind=BundleResourceKind.SKILL,
                name="Research",
                definition={"content": "A skill body"},
                included=frozenset(
                    {BundleContentLayer.DEFINITION}
                    | ({BundleContentLayer.SKILL_FILES} if asset is not None else set())
                ),
            ),
        ),
        assets=() if asset is None else (asset,),
    )


def _zip(manifest: ResourceBundle, content: bytes = b"# Instructions\n") -> BytesIO:
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest.model_dump_json())
        for path in {asset.archive_path for asset in manifest.assets}:
            archive.writestr(path, content)
    stream.seek(0)
    return stream


def test_graph_round_trip_preserves_shared_resources_and_cycles() -> None:
    manifest = _manifest()
    skill = manifest.resources[1].model_copy(
        update={"references": (BundleReference(path=("delegate",), target="agent/one"),)}
    )
    cyclic = manifest.model_copy(update={"resources": (manifest.resources[0], skill)})
    assert ResourceBundle.model_validate_json(cyclic.model_dump_json()) == cyclic
    assert cyclic.resources[0].definition["instructions"] == "A UUID in text stays text."


@pytest.mark.parametrize("path", [("items", -1), ("",), ("items", True)])
def test_reference_paths_refuse_ambiguous_or_negative_indexes(path: tuple[object, ...]) -> None:
    with pytest.raises(ValidationError):
        BundleReference.model_validate({"path": path, "target": "skill/one"})


@pytest.mark.parametrize(
    "name", ["../key", "/key", "a/../key", "a//key", "./key", "C:/key", "a\\key", "a\x00b"]
)
def test_logical_asset_names_cannot_escape_the_resource(name: str) -> None:
    with pytest.raises(ValidationError):
        BundleAsset.model_validate({**_asset().model_dump(), "name": name})


@pytest.mark.parametrize(
    "case",
    [
        "duplicate",
        "missing_root",
        "duplicate_root",
        "dangling",
        "owner",
        "layer",
        "asset_name",
        "size",
    ],
)
def test_manifest_refuses_inconsistent_resource_and_asset_graphs(case: str) -> None:
    asset = _asset()
    data = _manifest(asset).model_dump(mode="json")
    match case:
        case "duplicate":
            data["resources"].append(data["resources"][0])
        case "missing_root":
            data["roots"] = ["agent/missing"]
        case "duplicate_root":
            data["roots"] *= 2
        case "dangling":
            data["resources"][0]["references"][0]["target"] = "skill/missing"
        case "owner":
            data["assets"][0]["resource"] = "skill/missing"
        case "layer":
            data["assets"][0]["layer"] = "project_files"
        case "asset_name":
            data["assets"] *= 2
        case "size":
            duplicate = {**data["assets"][0], "name": "another.md", "size_bytes": 100}
            data["assets"].append(duplicate)
    with pytest.raises(ValidationError):
        ResourceBundle.model_validate(data)


@pytest.mark.parametrize("case", ["kind", "definition", "paths", "reference_only"])
def test_resource_definitions_match_their_selection_and_declared_paths(case: str) -> None:
    data = _manifest().resources[0].model_dump(mode="json")
    match case:
        case "kind":
            data["kind"] = "skill"
        case "definition":
            data["included"] = []
        case "paths":
            data["references"] *= 2
        case "reference_only":
            data["included"] = []
            data["definition"] = None
    with pytest.raises(ValidationError):
        BundleResource.model_validate(data)


def test_assets_stream_with_a_digest_and_do_not_close_the_upload() -> None:
    content = b"hello" * 30_000
    asset = _asset(content)
    stream = _zip(_manifest(asset), content)
    with open_bundle(stream) as bundle:
        chunks = list(bundle.asset_chunks(asset))
        assert b"".join(chunks) == content
        assert len(chunks) > 1
    assert not stream.closed


def test_empty_and_shared_content_is_verified_once_per_requested_asset() -> None:
    asset = _asset(b"")
    other = asset.model_copy(update={"name": "second.md"})
    manifest = _manifest(asset).model_copy(update={"assets": (asset, other)})
    with open_bundle(_zip(manifest, b"")) as bundle:
        assert list(bundle.asset_chunks(asset)) == []
        assert list(bundle.asset_chunks(other)) == []


def test_manifest_cannot_promise_content_that_is_not_present_or_is_different() -> None:
    manifest = _manifest(_asset())
    stream = _zip(manifest)
    with open_bundle(stream) as bundle, pytest.raises(BadRequestError, match="not declared"):
        list(bundle.asset_chunks(_asset(b"unknown")))
    with (
        open_bundle(_zip(manifest, b"x" * manifest.assets[0].size_bytes)) as bundle,
        pytest.raises(BadRequestError, match="digest"),
    ):
        list(bundle.asset_chunks(manifest.assets[0]))
    with (
        pytest.raises(BadRequestError, match="different size"),
        open_bundle(_zip(manifest, b"short")),
    ):
        pytest.fail("The manifest was not validated")


@pytest.mark.parametrize(
    "limit", ["compressed_bytes", "expanded_bytes", "manifest_bytes", "entry_bytes", "entries"]
)
def test_archive_limits_are_checked_before_consuming_assets(limit: str) -> None:
    limits = replace(BundleLimits(), **{limit: 1})
    with (
        pytest.raises(BadRequestError, match=r"limit|too many"),
        open_bundle(_zip(_manifest(_asset())), limits=limits),
    ):
        pytest.fail("The configured limit was ignored")


@pytest.mark.parametrize(
    "case",
    ["missing", "duplicate", "extra", "link", "directory", "invalid_manifest", "missing_asset"],
)
def test_archive_members_must_exactly_match_the_validated_manifest(case: str) -> None:
    stream = BytesIO()
    manifest = _manifest(_asset())
    with ZipFile(stream, "w") as archive:
        if case != "missing":
            archive.writestr(
                "manifest.json", "[]" if case == "invalid_manifest" else manifest.model_dump_json()
            )
        if case == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate"):
                archive.writestr("manifest.json", manifest.model_dump_json())
        if case == "extra":
            archive.writestr("../outside", b"bad")
        if case == "link":
            link = ZipInfo("link")
            link.external_attr = (S_IFLNK | 0o777) << 16
            archive.writestr(link, b"outside")
        if case == "directory":
            archive.writestr("folder/", b"")
        if case != "missing_asset":
            archive.writestr(manifest.assets[0].archive_path, b"# Instructions\n")
    with pytest.raises(BadRequestError), open_bundle(stream):
        pytest.fail("An invalid archive reached a consumer")


def test_malformed_zip_is_a_domain_refusal_and_consumer_errors_are_not_masked() -> None:
    with pytest.raises(BadRequestError, match="not a complete"), open_bundle(BytesIO(b"not a zip")):
        pytest.fail("Invalid upload")
    with pytest.raises(BadZipFile, match="consumer bug"), open_bundle(_zip(_manifest())):
        raise BadZipFile("consumer bug")


@pytest.mark.parametrize("member_kind", ["manifest", "asset"])
def test_corrupt_member_bytes_fail_crc_without_exposing_a_library_traceback(
    member_kind: str,
) -> None:
    asset = _asset()
    manifest = _manifest(asset)
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("manifest.json", manifest.model_dump_json())
        archive.writestr(asset.archive_path, b"# Instructions\n")
        name = "manifest.json" if member_kind == "manifest" else asset.archive_path
        member = archive.getinfo(name)
        offset = member.header_offset + 30 + len(member.filename.encode()) + len(member.extra)
    raw = bytearray(stream.getvalue())
    raw[offset] ^= 1
    with (
        pytest.raises(BadRequestError, match="corrupt or incomplete"),
        open_bundle(BytesIO(raw)) as bundle,
    ):
        list(bundle.asset_chunks(asset))


def test_rebinding_preserves_mcp_policy_and_uuid_shaped_application_data() -> None:
    from app.services.portability.mapping import rebind_definition

    source = uuid4()
    destination = uuid4()
    policy = {
        "allowed_tools": ["search", "read"],
        "approval": "all",
        "tool_approval": {"read": False},
    }
    resource = BundleResource(
        key="agent/one",
        kind=BundleResourceKind.AGENT,
        name="Researcher",
        included=frozenset({BundleContentLayer.DEFINITION}),
        definition={
            "mcp_servers": [{"connection_id": str(source), **policy}],
            "instructions": str(source),
            "custom_data": {"external_id": str(source)},
        },
        references=(
            BundleReference(path=("mcp_servers", 0, "connection_id"), target="mcp_connection/one"),
        ),
    )
    rebound = rebind_definition(resource, {"mcp_connection/one": destination})
    assert rebound.definition == {
        "mcp_servers": [{"connection_id": str(destination), **policy}],
        "instructions": str(source),
        "custom_data": {"external_id": str(source)},
    }
    assert resource.definition["mcp_servers"][0]["connection_id"] == str(source)
    assert rebound.skipped == ()


def test_explicit_skips_remove_the_intended_items_without_index_drift() -> None:
    from app.services.portability.mapping import rebind_definition

    resource = BundleResource(
        key="agent/one",
        kind=BundleResourceKind.AGENT,
        name="Researcher",
        included=frozenset({BundleContentLayer.DEFINITION}),
        definition={
            "skill_ids": ["a", "b", "c"],
            "model_profile_id": "model",
            "mcp_servers": [{"connection_id": "mcp", "approval": "all"}],
        },
        references=(
            BundleReference(path=("skill_ids", 0), target="skill/a"),
            BundleReference(path=("skill_ids", 1), target="skill/b"),
            BundleReference(path=("skill_ids", 2), target="skill/c"),
            BundleReference(path=("model_profile_id",), target="model_profile/one"),
            BundleReference(path=("mcp_servers", 0, "connection_id"), target="mcp_connection/one"),
        ),
    )
    kept = uuid4()
    result = rebind_definition(
        resource,
        {
            "skill/a": None,
            "skill/b": kept,
            "skill/c": None,
            "model_profile/one": None,
            "mcp_connection/one": None,
        },
        omit={("mcp_servers", 0, "connection_id"): ("mcp_servers", 0)},
    )
    assert result.definition == {"skill_ids": [str(kept)], "mcp_servers": []}
    assert len(result.skipped) == 4


@pytest.mark.parametrize(
    "case",
    [
        "reference_only",
        "missing_choice",
        "bad_path",
        "non_reference",
        "bad_omit",
        "outside_omit",
        "root_omit",
    ],
)
def test_rebinding_refuses_incomplete_or_inconsistent_mapping_plans(case: str) -> None:
    from app.services.portability.mapping import rebind_definition

    resource = _manifest().resources[0]
    choices = {"skill/one": None}
    omit = None
    match case:
        case "reference_only":
            resource = _manifest().resources[1].model_copy(update={"definition": None})
        case "missing_choice":
            choices = {}
        case "bad_path":
            resource = resource.model_copy(
                update={"references": (BundleReference(path=("missing",), target="skill/one"),)}
            )
        case "non_reference":
            resource = resource.model_copy(update={"definition": {"skill_ids": [True]}})
        case "bad_omit":
            omit = {("missing",): ("missing",)}
        case "outside_omit":
            omit = {("skill_ids", 0): ("instructions",)}
        case "root_omit":
            omit = {("skill_ids", 0): ()}
    with pytest.raises(BadRequestError):
        rebind_definition(resource, choices, omit=omit)


def test_skipping_a_nested_optional_pin_keeps_the_other_configuration() -> None:
    from app.services.portability.mapping import rebind_definition

    resource = BundleResource(
        key="agent/one",
        kind=BundleResourceKind.AGENT,
        name="Researcher",
        included=frozenset({BundleContentLayer.DEFINITION}),
        definition={"settings": {"profile": "source", "enabled": True}},
        references=(BundleReference(path=("settings", "profile"), target="model_profile/one"),),
    )
    result = rebind_definition(resource, {"model_profile/one": None})
    assert result.definition == {"settings": {"enabled": True}}
