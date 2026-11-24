"""Media requests are priced and supported before a workflow can spend."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.capabilities.image_generation import ImageGenerationConfig
from app.core.image_workflow_catalog import ImageOutputPrice, ImageWorkflowSupport
from app.services import video_models
from app.services.workflow_media_catalog import (
    image_support,
    media_binding_problems,
    reference_supported,
    video_support,
)
from app.workflows.contracts.io import Binding, FileRef, LiteralValue, NodeOutputRef
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from app.workflows.nodes._media_config import (
    ImageGenerateConfig,
    MediaGenerateInput,
    VideoGenerateConfig,
)

pytestmark = pytest.mark.security


def image_config(**changes: object) -> ImageGenerateConfig:
    return ImageGenerateConfig.model_validate(
        {"provider": "openai", "model": "gpt-image-1.5", "secret_id": uuid4(), **changes}
    )


@pytest.mark.parametrize(
    ("model", "expected", "tokens"),
    [
        ("gemini-3-pro-image", "1.114112", 8192),
        ("gemini-3.1-flash-image", "0.557056", 8192),
        ("gemini-3.1-flash-lite-image", "0.139264", 4096),
        ("gemini-2.5-flash-image", "0.265421", 8192),
    ],
)
def test_google_hold_covers_the_provider_input_limit_and_capped_output(
    model: str, expected: str, tokens: int
) -> None:
    config = image_config(provider="google", model=model)
    support = config.workflow_support()
    assert support.max_output_tokens == tokens
    assert config.reservation_usd() == Decimal(expected)
    assert support.reference_image
    assert support.pricing_as_of == date(2026, 11, 16)
    # No extra paid search tool or caller model is hidden in this accounting.
    assert support.tool_prompt_max_characters == 0
    assert not support.output_prices


def test_openai_hold_includes_the_caller_and_the_separate_single_image_tool() -> None:
    config = image_config()
    # Long-context caller input + capped caller output + the maximum UTF-8
    # tool prompt + the rounded-up, explicitly chosen image output price.
    expected = Decimal(1_050_000) * 5 + Decimal(8192) * Decimal("22.5") + 128_000 * 5
    expected = expected / 1_000_000 + Decimal("0.035")
    assert config.reservation_usd() == expected == Decimal("6.109320")
    request = config.request_config()
    assert (request.size, request.quality, request.background, request.output_format) == (
        "1024x1024",
        "medium",
        "opaque",
        "png",
    )
    assert image_config(quality="high").reservation_usd() == Decimal("6.208320")
    assert not config.workflow_support().reference_image


def test_gpt_image_2_estimates_do_not_establish_a_workflow_reservation_bound() -> None:
    # The provider's fixed output-token table explicitly excludes Image 2.
    # Its existing agent binding stays readable, but no workflow may spend on
    # the assumption that a displayed image estimate is a hard ceiling.
    assert ImageGenerationConfig(provider="openai", model="gpt-image-2").model == "gpt-image-2"
    with pytest.raises(ValidationError, match="verified workflow"):
        image_config(model="gpt-image-2")
    with pytest.raises(ValueError, match="verified workflow"):
        image_support("openai", "gpt-image-2")


@pytest.mark.parametrize("model,rate", [("gpt-image-1.5", "32"), ("gpt-image-1-mini", "8")])
def test_openai_output_hold_covers_the_documented_pre_2_token_table(model, rate) -> None:
    tokens = {
        "low": {"1024x1024": 272, "1024x1536": 408, "1536x1024": 400},
        "medium": {"1024x1024": 1056, "1024x1536": 1584, "1536x1024": 1568},
        "high": {"1024x1024": 4160, "1024x1536": 6240, "1536x1024": 6208},
    }
    for price in image_support("openai", model).output_prices:
        assert (
            price.output_ceiling_usd
            >= tokens[price.quality][price.size] * Decimal(rate) / 1_000_000
        )


@pytest.mark.parametrize(
    "change",
    [
        {"quality": "auto"},
        {"size": "auto"},
        {"aspect_ratio": "1:1"},
        {"background": "transparent", "output_format": "jpeg"},
        {"provider": "google", "model": "gemini-3.1-flash-lite-image", "size": "4K"},
        {"provider": "google", "model": "gemini-2.5-flash-image", "size": "1K"},
        {"provider": "google", "model": "gemini-3-pro-image", "quality": "high"},
        {"provider": "google", "model": "gemini-3-pro-image", "background": "opaque"},
        {"provider": "google", "model": "gemini-3-pro-image", "output_format": "png"},
        {"model": "gpt-image-1"},
        {"filename": "../outside.png"},
        {"filename": "unsafe\r\nheader.png"},
        {"timeout_seconds": 601},
        {"max_cost_usd": float("inf")},
    ],
)
def test_an_ignored_incompatible_or_unbounded_option_is_refused(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        image_config(**change)


def test_legacy_agent_bindings_stay_readable_and_google_omits_unsupported_knobs() -> None:
    assert ImageGenerationConfig(provider="openai", model="gpt-image-1").model == "gpt-image-1"
    request = image_config(provider="google", model="gemini-2.5-flash-image").request_config()
    assert request.size is None
    assert request.output_format is None
    assert request.background is None
    assert request.quality is None
    assert request.aspect_ratio == "1:1"
    assert image_config(background="transparent", output_format="webp").request_config()


def test_missing_catalog_metadata_does_not_mean_free_or_supported() -> None:
    with pytest.raises(ValueError, match="verified workflow"):
        image_support("missing", "missing")
    with pytest.raises(ValueError, match="verified workflow"):
        image_support("openai", "missing")
    support = image_support("openai", "gpt-image-1.5")
    with pytest.raises(ValueError, match="verified output ceiling"):
        support.reservation_usd(size="auto", quality="high")


@pytest.mark.parametrize(
    "change",
    [
        {"defaults": {"size": "4K"}},
        {"qualities": ["low", "low", "medium", "high"]},
        {"reference_image": True},
        {"output_prices": []},
        {"tool_prompt_max_characters": 0},
        {"max_output_tokens": 0},
        {"input_usd_per_million": "Infinity"},
    ],
)
def test_invalid_catalog_bounds_fail_closed(change: dict[str, object]) -> None:
    data = image_support("openai", "gpt-image-1.5").model_dump()
    with pytest.raises(ValidationError):
        ImageWorkflowSupport.model_validate({**data, **change})


def test_duplicate_or_understated_output_prices_are_refused() -> None:
    data = image_support("openai", "gpt-image-1.5").model_dump()
    rows = data["output_prices"]
    with pytest.raises(ValidationError, match="Duplicate image output"):
        ImageWorkflowSupport.model_validate({**data, "output_prices": [*rows, rows[0]]})
    with pytest.raises(ValidationError, match="below its estimate"):
        ImageOutputPrice(
            size="1024x1024", quality="low", output_estimate_usd="1", output_ceiling_usd="0"
        )


def graph_with_reference(
    *,
    provider: str | None = "openai",
    model: str = "gpt-image-1.5",
    kind: str = "image.generate",
    source: object = "file",
    disabled: bool = False,
    version: int = 1,
) -> WorkflowGraph:
    node_id = uuid4()
    config = {"model": model}
    if provider is not None:
        config["provider"] = provider
    value = (
        FileRef(file_id=uuid4(), content_type="image/png", byte_size=10)
        if source == "file"
        else source
    )
    return WorkflowGraph(
        entry_node_id=node_id,
        nodes=(
            NodeInstance(
                id=node_id,
                definition_id=kind,
                definition_version=version,
                config=config,
                layout=NodePosition(x=0, y=0),
                disabled=disabled,
            ),
        ),
        bindings=(
            Binding(
                target_node_id=node_id,
                target_field="reference_image",
                source=LiteralValue(value=value),
            ),
        ),
    )


def test_reference_binding_is_refused_before_publication_even_when_its_value_is_dynamic() -> None:
    graph = graph_with_reference()
    assert media_binding_problems(graph)[0][0] == "bindings.0.source"
    dynamic = graph.model_copy(
        update={
            "bindings": (
                graph.bindings[0].model_copy(
                    update={
                        "source": NodeOutputRef(node_id=uuid4(), port="out", field_path=("file",))
                    }
                ),
            )
        }
    )
    assert media_binding_problems(dynamic)
    assert media_binding_problems(graph_with_reference(provider=None))
    assert not media_binding_problems(
        graph_with_reference(provider="google", model="gemini-3-pro-image")
    )
    assert not media_binding_problems(graph_with_reference(source=None))
    assert not media_binding_problems(graph_with_reference(disabled=True))
    assert not media_binding_problems(graph_with_reference(version=2))
    assert not media_binding_problems(graph_with_reference(kind="debug.echo"))
    assert not media_binding_problems(graph.model_copy(update={"bindings": ()}))
    prompt_binding = graph.bindings[0].model_copy(update={"target_field": "prompt"})
    assert not media_binding_problems(graph.model_copy(update={"bindings": (prompt_binding,)}))


def test_unrecognized_reference_contracts_and_unknown_binding_targets_are_refused_safely() -> None:
    assert not reference_supported("image.generate", "missing", "missing")
    assert not reference_supported("video.generate", "missing", "missing")
    assert not reference_supported("debug.echo", "google", "gemini-3-pro-image")
    graph = graph_with_reference()
    other = graph.bindings[0].model_copy(update={"target_node_id": uuid4()})
    assert not media_binding_problems(graph.model_copy(update={"bindings": (other,)}))


def test_video_reuses_current_catalog_prices_and_refuses_missing_prices() -> None:
    for provider in video_models.providers():
        for model in provider.models:
            support = video_support(model)
            assert support is not None
            config = VideoGenerateConfig(
                provider=provider.provider, model=model.id, secret_id=uuid4()
            )
            seconds = config.requested_seconds() or model.max_seconds
            request = config.request_config()
            assert request.resolution == support.defaults.resolution
            assert request.aspect_ratio == support.defaults.aspect_ratio
            assert request.seconds == support.defaults.seconds
            assert request.audio == support.defaults.audio
            if model.audio == "optional":
                assert request.audio is False
                sounding = config.model_copy(update={"audio": True})
                # The shared catalog prices optional sound at its sound-on rate.
                assert sounding.reservation_usd() == config.reservation_usd()
            assert (
                config.reservation_usd() == support.usd_per_second[model.resolutions[0]] * seconds
            )
            assert (
                reference_supported("video.generate", provider.provider, model.id)
                == model.first_frame
            )
    model = video_models.providers()[0].models[0]
    assert video_support(replace(model, prices=())) is None
    assert video_support(model, on=date(1900, 1, 1)) is None
    assert video_support(replace(model, resolutions=())) is None
    assert video_support(replace(model, aspect_ratios=())) is None
    price = replace(model.prices[-1], since=date(2000, 1, 1), usd_per_second={})
    assert video_support(replace(model, prices=(price,))) is None
    for invalid in (Decimal("NaN"), Decimal("0"), Decimal("-1")):
        price = replace(price, usd_per_second=dict.fromkeys(model.resolutions, invalid))
        assert video_support(replace(model, prices=(price,))) is None


def test_video_options_and_catalog_availability_are_checked_before_spending() -> None:
    provider = video_models.providers()[0]
    model = provider.models[0]
    config = {"provider": provider.provider, "model": model.id, "secret_id": uuid4()}
    for changes in (
        {"resolution": "unpriced"},
        {"aspect_ratio": "100:1"},
        {"seconds": model.max_seconds + 1},
        {"provider": "missing"},
        {"model": "missing"},
        {"base_url": "https://example.com"},
    ):
        with pytest.raises(ValidationError):
            VideoGenerateConfig.model_validate({**config, **changes})
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("app.workflows.nodes._media_config.video_support", lambda _: None)
        with pytest.raises(ValidationError, match="no current catalog price"):
            VideoGenerateConfig.model_validate(config)
    valid = VideoGenerateConfig.model_validate(config)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "app.workflows.nodes._media_config.price_per_second", lambda *_args, **_kwargs: None
        )
        with pytest.raises(ValueError, match="no current catalog price"):
            valid.reservation_usd()


def test_inputs_have_one_scoped_file_and_a_bounded_prompt() -> None:
    with pytest.raises(ValidationError):
        MediaGenerateInput(prompt=" ")
    with pytest.raises(ValidationError):
        MediaGenerateInput(prompt="x" * 16_001)
    with pytest.raises(ValidationError):
        MediaGenerateInput.model_validate(
            {"prompt": "draw", "reference_image": "https://example.com/a.png"}
        )
    value = MediaGenerateInput(prompt="  draw  ")
    assert value.prompt == "draw" and value.reference_image is None
