"""Bytes remain bytes across the skill storage/transport boundary."""

import base64

import pytest

from app.core.skill_files import (
    MAX_SKILL_FILE_BYTES,
    decode_skill_file,
    encode_skill_file,
)


@pytest.mark.parametrize(
    "raw", [b"", b"  exact text\n", "zażółć".encode(), b"pdf\x00bytes", b"\xff\x80"]
)
def test_lossless_deterministic_encoding(raw: bytes) -> None:
    body = encode_skill_file(raw)
    assert decode_skill_file(body.content, body.encoding) == raw
    assert encode_skill_file(decode_skill_file(body.content, body.encoding)) == body


@pytest.mark.parametrize("content", ["%%%", "eA==\n", "eA", "eh==", "ż"])
def test_noncanonical_binary_payload_is_refused(content: str) -> None:
    with pytest.raises(ValueError, match="canonical base64"):
        decode_skill_file(content, "base64")


def test_text_nul_needs_binary_encoding() -> None:
    with pytest.raises(ValueError, match="NUL"):
        decode_skill_file("zero\0byte")


def test_exact_file_limit_and_both_decoded_size_guards() -> None:
    raw = b"a" * MAX_SKILL_FILE_BYTES
    assert decode_skill_file(encode_skill_file(raw).content) == raw
    with pytest.raises(ValueError, match="8 MiB"):
        encode_skill_file(raw + b"a")
    with pytest.raises(ValueError, match="8 MiB"):
        decode_skill_file(raw.decode() + "a")
    # One extra byte can share the maximum encoded length, so decoded length
    # remains a separate check rather than trusting the base64 character bound.
    with pytest.raises(ValueError, match="8 MiB"):
        decode_skill_file(base64.b64encode(raw + b"a").decode(), "base64")
    with pytest.raises(ValueError, match="8 MiB"):
        decode_skill_file("A" * (4 * ((MAX_SKILL_FILE_BYTES + 2) // 3) + 4), "base64")


def test_inert_metadata_keeps_safe_json_values() -> None:
    from app.core.skill_files import validate_skill_metadata

    metadata = {
        "license": "MIT",
        "allowed-tools": ["execute"],
        "metadata": {"revision": 2, "ready": True, "notes": None},
    }
    assert validate_skill_metadata(metadata) == metadata


@pytest.mark.parametrize(
    "value",
    [
        [],
        {1: "key"},
        {"name": "other"},
        {"description": "other"},
        {"nul": "bad\0"},
        {"bad\0": "key"},
        {"number": float("inf")},
        {"date": object()},
        {"large": "a" * (64 * 1024)},
    ],
)
def test_unsafe_or_ambiguous_metadata_is_refused(value: object) -> None:
    from app.core.skill_files import validate_skill_metadata

    with pytest.raises(ValueError):
        validate_skill_metadata(value)


def test_metadata_cycles_depth_and_breadth_are_bounded() -> None:
    from app.core.skill_files import validate_skill_metadata

    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    with pytest.raises(ValueError, match="cycles"):
        validate_skill_metadata(cyclic)
    nested: object = "leaf"
    for _ in range(14):
        nested = [nested]
    with pytest.raises(ValueError, match="nesting"):
        validate_skill_metadata({"deep": nested})
    with pytest.raises(ValueError, match="value-count"):
        validate_skill_metadata({"many": [None] * 4096})


def test_metadata_equality_is_json_typed_and_order_independent() -> None:
    from app.core.skill_files import same_skill_metadata

    assert same_skill_metadata({"a": 1, "b": [None]}, {"b": [None], "a": 1})
    assert not same_skill_metadata({"value": True}, {"value": 1})


def test_metadata_three_way_merge_preserves_disjoint_changes_and_deletions() -> None:
    from app.services.skill_catch_up import merge_manifest_metadata

    assert merge_manifest_metadata(
        {"license": "MIT", "remove": "old"},
        {"license": "Apache-2.0"},
        {"license": "MIT", "remove": "old", "allowed-tools": ["execute"]},
    ) == {"license": "Apache-2.0", "allowed-tools": ["execute"]}
    assert merge_manifest_metadata({"a": None}, {}, {"a": None}) == {}


def test_metadata_merge_conflicts_do_not_leak_or_guess_values() -> None:
    from app.core.exceptions import ConflictError
    from app.services.skill_catch_up import merge_manifest_metadata

    with pytest.raises(ConflictError) as caught:
        merge_manifest_metadata(
            {"license": "MIT"}, {"license": "secret-left"}, {"license": "secret-right"}
        )
    assert caught.value.details == {"field": "manifest_metadata", "key": "license"}
    assert "secret" not in str(caught.value)
