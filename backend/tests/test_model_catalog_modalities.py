"""What a provider's listing says a model emits, and the ten new listings."""

import pytest

from app.services.model_catalog import LISTINGS, ListingSpec, _modalities, _read_listing

pytestmark = pytest.mark.anyio


def test_a_listing_that_states_output_modalities_is_read():
    # OpenRouter's own shape, which is why the field exists: it is the one public
    # listing that says which models emit an image.
    spec = ListingSpec(
        url="https://example.test/models",
        array_path="data",
        id_field="id",
        modalities_path="architecture.output_modalities",
    )
    models = _read_listing(
        {
            "data": [
                {"id": "a", "architecture": {"output_modalities": ["text", "image"]}},
                {"id": "b", "architecture": {"output_modalities": ["text"]}},
            ]
        },
        spec,
    )

    assert {model.id: model.output_modalities for model in models} == {
        "a": ("text", "image"),
        "b": ("text",),
    }


def test_a_listing_that_says_nothing_leaves_it_empty_rather_than_guessing():
    # Empty means "not stated", never "text only": a client that read absence as a
    # refusal would hide every model on the nine listings that carry no such field.
    spec = ListingSpec(url="https://example.test/models", array_path="data", id_field="id")

    models = _read_listing({"data": [{"id": "a"}]}, spec)

    assert models[0].output_modalities == ()


@pytest.mark.parametrize(
    "row",
    [
        {"architecture": "text"},
        {"architecture": {"output_modalities": "image"}},
        {"architecture": {"output_modalities": [None, 3]}},
        {},
    ],
)
def test_a_shape_that_moved_reads_as_nothing_stated(row: dict[str, object]):
    # A listing whose shape has changed is a listing this cannot interpret, and a
    # picker filtering on the wreckage is worse than one filtering on nothing.
    assert _modalities(row, "architecture.output_modalities") == ()


def test_every_public_listing_is_reachable_without_a_credential():
    # The four added because they need no key are the ones worth most: the picker
    # fills in before anybody has stored a credential for that provider.
    keyless = {name for name, spec in LISTINGS.items() if spec.auth_header is None}

    assert {"openrouter", "sambanova", "vercel", "ovhcloud", "huggingface"} <= keyless


def test_every_keyed_listing_says_how_to_authenticate():
    # A spec with a header and no template would send the word "Bearer" and the
    # provider would answer 401 for a key that is in fact stored.
    for name, spec in LISTINGS.items():
        if spec.auth_header is not None:
            assert "{key}" in spec.auth_template, name
