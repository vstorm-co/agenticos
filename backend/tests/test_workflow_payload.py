"""Inline JSON uses encoded bytes, with refusal before accumulating serialized text."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from app.workflows.contracts.payload import PayloadTooLarge, json_byte_size

pytestmark = pytest.mark.security


@pytest.mark.parametrize("value", [None, {}, [], {"text": "Zażółć 😀\n", "n": [1, True, None]}])
def test_size_matches_compact_utf8_json(value):
    expected = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
    assert json_byte_size(value, limit=expected) == expected
    with pytest.raises(PayloadTooLarge):
        json_byte_size(value, limit=expected - 1)


def test_unicode_can_cross_the_byte_budget_without_crossing_the_character_budget():
    with pytest.raises(PayloadTooLarge):
        json_byte_size("😀", limit=5)


@pytest.mark.parametrize("value", [float("nan"), object()])
def test_invalid_json_is_not_disguised_as_a_size_failure(value):
    with pytest.raises((ValueError, TypeError)) as raised:
        json_byte_size(value, limit=1000)
    assert not isinstance(raised.value, PayloadTooLarge)


def test_models_are_projected_shallowly_and_scalar_adapters_are_supported():
    class Output(BaseModel):
        at: datetime

    value = Output(at=datetime(2026, 10, 24, tzinfo=UTC))
    assert json_byte_size(value, limit=100) == len('{"at":"2026-10-24T00:00:00Z"}')
