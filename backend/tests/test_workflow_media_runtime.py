"""Media prices, read contracts and registration never invent spend or authority."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic_ai.messages import BinaryImage, FilePart, ModelResponse, TextPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.workflow_media_operation import WorkflowMediaOperation
from app.schemas.workflow_media import (
    ImageMediaEstimateRequest,
    VideoMediaEstimateRequest,
    WorkflowMediaEstimateAssumption,
)
from app.services import video_models, workflow_media_read
from app.services.organization_secret import OrganizationSecretService
from app.services.workflow_media import _pricing
from app.services.workflow_media._errors import MediaOperationError
from app.services.workflow_media._image_model import DurableImageModel
from app.services.workflow_media._pricing import CostFact, ImageCostEvidence, VideoCostEvidence
from app.services.workflow_media_read import WorkflowMediaReadService, retry_effect
from app.workflows import _registry
from app.workflows.contracts.results import Completed
from app.workflows.nodes import _media_handler
from app.workflows.nodes._media_config import (
    ImageGenerateConfig,
    MediaGenerateInput,
    VideoGenerateConfig,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


class EmptyModel(BaseModel):
    pass


def image_config(**changes):
    return ImageGenerateConfig.model_validate(
        {"provider": "openai", "model": "gpt-image-1.5", "secret_id": uuid4(), **changes}
    )


def video_config(*, variable=False, **changes):
    provider, model = next(
        (provider, model)
        for provider in video_models.providers()
        for model in provider.models
        if model.duration_choosable is not variable
    )
    return VideoGenerateConfig.model_validate(
        {"provider": provider.provider, "model": model.id, "secret_id": uuid4(), **changes}
    )


@pytest.mark.parametrize("reported", [False, True])
@pytest.mark.parametrize("returned", [False, True])
@pytest.mark.parametrize("tier", [None, "default"])
def test_image_fee_evidence_keeps_native_tool_input_unresolved(
    monkeypatch, reported, returned, tier
):
    config = image_config()
    basis = _pricing.snapshot(config)
    entry = SimpleNamespace(priced=True, provider_reported=reported, cost_usd=Decimal("0.012"))
    ledger = Mock()
    ledger.record.return_value = entry
    monkeypatch.setattr(_pricing, "SpendLedger", lambda: ledger)
    parts = [TextPart("private revised prompt: never an accounting completeness proof")]
    if returned:
        parts.append(FilePart(content=BinaryImage(data=b"image", media_type="image/png")))
    response = ModelResponse(
        parts=parts,
        model_name="gpt-5.4",
        provider_name="openai",
        provider_details={"service_tier": tier} if tier is not None else None,
        usage=RequestUsage(input_tokens=7, output_tokens=3, cache_read_tokens=2),
    )
    fact = _pricing.image_cost(basis, response)
    assert (
        fact.incurred_usd == Decimal("0.046") if returned else fact.incurred_usd == Decimal("0.012")
    )
    assert fact.held_usd == (Decimal("0.640000") if returned else Decimal("0.675000"))
    assert fact.source == "catalog_estimate" and not fact.complete
    assert fact.evidence.tool_input_reconciled is False
    assert fact.evidence.unexpected_service_tier is False
    assert fact.evidence.cache_read_tokens == 2
    assert "private" not in fact.model_dump_json() and "revised" not in fact.model_dump_json()
    ledger.record.assert_called_once_with("gpt-5.4", response.usage, "openai")


@pytest.mark.parametrize("tier", ["priority", "future-priced-tier"])
@pytest.mark.parametrize("returned", [False, True])
def test_unexpected_image_service_tier_preserves_the_full_hold_without_a_standard_price_claim(
    monkeypatch, tier, returned
):
    config = image_config()
    basis = _pricing.snapshot(config)
    monkeypatch.setattr(
        _pricing,
        "SpendLedger",
        lambda: SimpleNamespace(
            record=lambda *_: SimpleNamespace(
                priced=True, provider_reported=False, cost_usd=Decimal("0.012")
            )
        ),
    )
    response = ModelResponse(
        parts=[FilePart(content=BinaryImage(data=b"image", media_type="image/png"))]
        if returned
        else [],
        model_name="gpt-5.4",
        provider_name="openai",
        provider_details={"service_tier": tier},
        usage=RequestUsage(input_tokens=7, output_tokens=3),
    )
    fact = _pricing.image_cost(basis, response)
    assert fact.incurred_usd == 0 and fact.held_usd == config.reservation_usd()
    assert fact.source == "catalog_estimate" and not fact.complete
    assert not fact.evidence.caller_priced and fact.evidence.unexpected_service_tier
    assert fact.evidence.image_returned is returned
    assert tier not in fact.model_dump_json()


@pytest.mark.parametrize("known,used", [(False, True), (True, False)])
def test_missing_or_empty_usage_keeps_the_caller_ceiling(monkeypatch, known, used):
    basis = _pricing.snapshot(image_config())
    monkeypatch.setattr(
        _pricing,
        "SpendLedger",
        lambda: SimpleNamespace(
            record=lambda *_: SimpleNamespace(
                priced=known, provider_reported=False, cost_usd=Decimal(0)
            )
        ),
    )
    response = ModelResponse(
        parts=[TextPart("No image")], usage=RequestUsage(input_tokens=int(used))
    )
    fact = _pricing.image_cost(basis, response)
    assert fact.incurred_usd == 0 and fact.held_usd == image_config().reservation_usd()
    assert not fact.evidence.caller_priced


def test_google_reported_usage_has_no_separate_native_tool_fee(monkeypatch):
    from app.services.image_models import image_providers

    model = next(
        model
        for provider in image_providers()
        if provider.provider == "google"
        for model in provider.models
        if model.workflow
    )
    basis = _pricing.snapshot(image_config(provider="google", model=model.id))
    monkeypatch.setattr(
        _pricing,
        "SpendLedger",
        lambda: SimpleNamespace(
            record=lambda *_: SimpleNamespace(
                priced=True, provider_reported=True, cost_usd=Decimal("0.023")
            )
        ),
    )
    fact = _pricing.image_cost(basis, ModelResponse(parts=[], usage=RequestUsage()))
    assert fact.incurred_usd == Decimal("0.023") and fact.held_usd == 0
    assert fact.source == "reported" and fact.complete


@pytest.mark.parametrize("variable", [False, True])
def test_video_books_observed_duration_not_its_maximum_hold(variable):
    config = video_config(variable=variable)
    basis = _pricing.snapshot(config)
    assert (basis.requested_seconds is None) is variable
    seconds = Decimal("1.25")
    fact = _pricing.video_cost(basis, seconds=seconds)
    assert fact.incurred_usd == (basis.usd_per_second * seconds).quantize(Decimal("0.000001"))
    assert fact.incurred_usd < config.reservation_usd()
    assert fact.source == "catalog_estimate" and fact.complete and fact.held_usd == 0
    assert fact.evidence.seconds == seconds


def test_unknown_dated_video_price_cannot_be_frozen(monkeypatch):
    config = video_config()
    monkeypatch.setattr(_pricing, "video_support", lambda _: None)
    with pytest.raises(ValueError, match="current catalog price"):
        _pricing.snapshot(config)


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf"), 3601])
def test_invalid_cost_evidence_is_refused(seconds):
    with pytest.raises(ValidationError):
        VideoCostEvidence(seconds=seconds)


def test_complete_accounting_cannot_hide_an_unresolved_hold():
    with pytest.raises(ValidationError, match="retain an unknown fee"):
        CostFact(
            incurred_usd=1,
            held_usd=1,
            source="reported",
            complete=True,
            evidence=VideoCostEvidence(seconds=1),
        )
    with pytest.raises(ValidationError):
        ImageCostEvidence(
            input_tokens=1,
            output_tokens=1,
            cache_read_tokens=0,
            caller_priced=True,
            image_returned=True,
            tool_input_reconciled=True,
        )


@pytest.mark.parametrize(
    "kind,cap", [("image", None), ("image", 0.01), ("video", None), ("variable", 100)]
)
async def test_estimate_uses_authorized_metadata_and_structured_assumptions_without_unwrapping(
    monkeypatch, kind, cap
):
    config = (
        image_config(max_cost_usd=cap)
        if kind == "image"
        else video_config(variable=kind == "variable", max_cost_usd=cap)
    )
    request = (
        ImageMediaEstimateRequest(kind="image", config=config)
        if kind == "image"
        else VideoMediaEstimateRequest(kind="video", config=config)
    )
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    metadata = AsyncMock(return_value=SimpleNamespace(id=config.secret_id))
    unwrap = AsyncMock(side_effect=AssertionError("An estimate must not unwrap"))
    monkeypatch.setattr(OrganizationSecretService, "workflow_media_secret", metadata)
    monkeypatch.setattr(OrganizationSecretService, "workflow_media_key", unwrap)
    estimate = await WorkflowMediaReadService(Mock()).estimate(ctx, request)
    assert estimate.reservation_usd == config.reservation_usd()
    assert estimate.sufficient_max_cost_usd is (
        cap is None or Decimal(str(cap)) >= estimate.reservation_usd
    )
    assert estimate.deficit_usd == (
        max(estimate.reservation_usd - Decimal(str(cap)), 0) if cap is not None else 0
    )
    assert estimate.model_dump(mode="json")["reservation_usd"] == str(estimate.reservation_usd)
    metadata.assert_awaited_once_with(ctx, config.secret_id, provider=config.provider)
    unwrap.assert_not_awaited()
    for item in estimate.assumptions:
        TypeAdapter(WorkflowMediaEstimateAssumption).validate_python(item.model_dump())
        assert "message" not in item.model_dump()


async def test_estimate_cannot_read_an_inaccessible_key(monkeypatch):
    monkeypatch.setattr(
        OrganizationSecretService,
        "workflow_media_secret",
        AsyncMock(side_effect=NotFoundError(message="Secret not found")),
    )
    with pytest.raises(NotFoundError):
        await WorkflowMediaReadService(Mock()).estimate(
            AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"),
            ImageMediaEstimateRequest(kind="image", config=image_config()),
        )


@pytest.mark.parametrize(
    "phase,receipt,digest,effect,kind",
    [
        ("prepared", False, False, "none", "video"),
        ("submitting", False, False, "reconciliation_required", "video"),
        ("unknown", False, False, "reconciliation_required", "video"),
        ("submitted", True, False, "collect_existing", "video"),
        ("collecting", True, True, "recover_output", "video"),
        ("stored", False, True, "recover_output", "video"),
        ("failed", True, True, "new_billable_submission", "video"),
        ("cancelled", False, False, "new_billable_submission", "video"),
        # An image receipt is billing evidence; it cannot collect the image again.
        ("submitted", True, False, "reconciliation_required", "image"),
    ],
)
def test_retry_label_never_suggests_new_submission_for_an_unknown_effect(
    phase, receipt, digest, effect, kind
):
    operation = WorkflowMediaOperation(
        phase=phase,
        media_kind=kind,
        provider_receipt={"id": "opaque"} if receipt else None,
        output_sha256="a" * 64 if digest else None,
    )
    assert retry_effect(operation) == effect


async def test_operation_projection_contains_only_authorized_status_and_total_unresolved_usd(
    monkeypatch,
):
    node_id = uuid4()
    operation = WorkflowMediaOperation(
        id=uuid4(),
        node_run_id=node_id,
        phase="unknown",
        held_usd=Decimal(2),
        incurred_usd=Decimal(1),
        booked_usd=Decimal("0.5"),
        cost_source="catalog_estimate",
        accounting_complete=False,
        provider_receipt=None,
        output_sha256=None,
        secret_id=uuid4(),
        pricing_snapshot={"private": "not public"},
    )
    lookup = AsyncMock(return_value={node_id: (operation, Decimal("7.5"))})
    monkeypatch.setattr(workflow_media_read.media_repo, "current_for_nodes", lookup)
    org_id, run_id = uuid4(), uuid4()
    result = await WorkflowMediaReadService(Mock()).for_nodes(
        organization_id=org_id, workflow_run_id=run_id, node_run_ids=[node_id]
    )
    public = result[node_id].model_dump(mode="json")
    assert public["node_unresolved_usd"] == "7.5" and public["held_usd"] == "2"
    assert public["cost_source"] == "catalog_estimate" and not public["accounting_complete"]
    assert set(public) == {
        "operation_id",
        "phase",
        "held_usd",
        "incurred_usd",
        "booked_usd",
        "cost_source",
        "accounting_complete",
        "node_unresolved_usd",
        "has_receipt",
        "retry_effect",
    }
    lookup.assert_awaited_once_with(
        lookup.await_args.args[0],
        organization_id=org_id,
        workflow_run_id=run_id,
        node_run_ids=[node_id],
    )


@pytest.mark.parametrize("kind", ["image", "video"])
async def test_disabled_generation_keeps_its_registered_schema_but_refuses_publication_and_execution(
    monkeypatch, kind
):
    monkeypatch.setattr(settings, f"WORKFLOW_{kind.upper()}_GENERATION_ENABLED", False)
    definition = _registry.get(f"{kind}.generate", 1)
    assert definition.retry_guarantee == "none" and definition.spends_budget
    assert definition.available() is False
    assert await definition.resource_check(Mock(), Mock(), EmptyModel())
    result = await definition.handler(None, None)
    assert result.error.code == "MEDIA_DISABLED" and not result.error.bypassable


@pytest.mark.parametrize("kind", ["image", "video"])
async def test_enabled_nodes_keep_validation_and_metadata_authority_before_execution(
    monkeypatch, kind
):
    monkeypatch.setattr(settings, f"WORKFLOW_{kind.upper()}_GENERATION_ENABLED", True)
    definition = _registry.get(f"{kind}.generate", 1)
    assert definition.available()
    assert (await definition.resource_check(Mock(), Mock(), EmptyModel()))[0][0] == ""
    assert (await definition.handler(None, None)).error.code == "MEDIA_STEP_NOT_CONFIGURED"
    config = image_config() if kind == "image" else video_config()
    metadata = AsyncMock(side_effect=NotFoundError(message="Secret not found"))
    monkeypatch.setattr(OrganizationSecretService, "workflow_media_secret", metadata)
    assert (await definition.resource_check(Mock(), Mock(), config))[0][0] == "secret_id"
    metadata.side_effect = None
    assert not await definition.resource_check(Mock(), Mock(), config)
    assert (
        await definition.resource_check(
            Mock(), Mock(), config.model_copy(update={"max_cost_usd": 0.000001})
        )
    )[0][0] == "max_cost_usd"
    generate = AsyncMock(return_value=Completed(output=EmptyModel()))
    monkeypatch.setattr(_media_handler, "generate", generate)
    supplied = MediaGenerateInput(prompt="Synthetic")
    assert isinstance(await definition.handler(config, supplied), Completed)
    generate.assert_awaited_once_with(config, supplied)


async def test_streaming_cannot_bypass_the_single_durable_image_request():
    journal = Mock()
    model = FunctionModel(lambda *_: ModelResponse(parts=[TextPart("not called")]))
    wrapped = DurableImageModel(model, journal, _pricing.snapshot(image_config()))
    with pytest.raises(MediaOperationError, match="single journaled response"):
        async with wrapped.request_stream([], None, ModelRequestParameters()):
            pytest.fail("The durable image boundary must refuse streaming")
    journal.start.assert_not_called()
