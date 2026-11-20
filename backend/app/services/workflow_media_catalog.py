"""Resolve workflow media options from the same catalogs the agent tools use."""

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from app.core.image_workflow_catalog import ImageWorkflowDefaults, ImageWorkflowSupport
from app.core.video_workflow_catalog import VideoWorkflowDefaults, VideoWorkflowSupport
from app.services import image_models, video_models
from app.workflows.contracts.io import LiteralValue, target_path

if TYPE_CHECKING:
    from app.services.video_models import VideoModel
    from app.workflows.graph.model import WorkflowGraph


def image_support(provider: str, model: str) -> ImageWorkflowSupport:
    entry = image_models.by_provider(provider)
    chosen = next((row for row in entry.models if row.id == model), None) if entry else None
    if chosen is None or chosen.workflow is None:
        raise ValueError("This image model has no verified workflow generation contract")
    return chosen.workflow


def image_options(
    provider: str, model: str, config: ImageWorkflowDefaults
) -> ImageWorkflowDefaults:
    support = image_support(provider, model)
    selected: dict[str, object] = {}
    for field, choices in (
        ("quality", support.qualities),
        ("size", support.sizes),
        ("aspect_ratio", support.aspect_ratios),
        ("background", support.backgrounds),
        ("output_format", support.output_formats),
    ):
        value = getattr(config, field)
        if value is None:
            value = getattr(support.defaults, field)
        if value is not None and value not in choices:
            raise ValueError(f"This image model does not support the workflow {field} setting")
        selected[field] = value
    options = ImageWorkflowDefaults.model_validate(selected)
    if options.background == "transparent" and options.output_format == "jpeg":
        raise ValueError("Transparent images require PNG or WebP output")
    return options


def video_defaults(model: VideoModel) -> VideoWorkflowDefaults:
    """The explicit workflow request defaults, also rendered by the editor."""
    return VideoWorkflowDefaults(
        resolution=model.resolutions[0],
        aspect_ratio=model.aspect_ratios[0],
        seconds=(
            min(max(video_models.USUAL_SECONDS, model.min_seconds), model.max_seconds)
            if model.duration_choosable
            else None
        ),
        audio=False if model.audio == "optional" else None,
    )


def video_support(model: VideoModel, *, on: date | None = None) -> VideoWorkflowSupport | None:
    today = on or datetime.now(UTC).date()
    applicable = [price for price in model.prices if price.since <= today]
    if not applicable:
        return None
    latest = max(applicable, key=lambda price: price.since)
    if (
        not model.resolutions
        or not model.aspect_ratios
        or any(
            resolution not in latest.usd_per_second
            or not latest.usd_per_second[resolution].is_finite()
            or latest.usd_per_second[resolution] <= 0
            for resolution in model.resolutions
        )
    ):
        return None
    return VideoWorkflowSupport(
        reference_image=model.first_frame,
        defaults=video_defaults(model),
        pricing_as_of=latest.since,
        usd_per_second={name: latest.usd_per_second[name] for name in model.resolutions},
    )


def reference_supported(kind: str, provider: str, model: str) -> bool:
    if kind == "image.generate":
        try:
            return image_support(provider, model).reference_image
        except ValueError:
            return False
    if kind == "video.generate":
        entry = video_models.by_provider(provider)
        chosen = entry.model(model) if entry else None
        support = video_support(chosen) if chosen else None
        return support is not None and support.reference_image
    return False


def media_binding_problems(graph: WorkflowGraph) -> list[tuple[str, str]]:
    """A bound image needs a statically verified provider contract at publication."""
    problems: list[tuple[str, str]] = []
    nodes = graph.node_by_id
    for index, binding in enumerate(graph.bindings):
        if target_path(binding.target_field)[0] != "reference_image":
            continue
        node = nodes.get(binding.target_node_id)
        if (
            node is None
            or node.disabled
            or node.definition_version != 1
            or node.definition_id not in {"image.generate", "video.generate"}
        ):
            continue
        if isinstance(binding.source, LiteralValue) and binding.source.value is None:
            continue
        provider, model = node.config.get("provider"), node.config.get("model")
        if not isinstance(provider, str) or not isinstance(model, str):
            message = "A reference image requires a fixed catalog provider and model"
        elif reference_supported(node.definition_id, provider, model):
            continue
        else:
            message = "This model has no verified workflow reference-image contract"
        problems.append((f"bindings.{index}.source", message))
    return problems
