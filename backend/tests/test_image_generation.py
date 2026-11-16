"""The image generation capability: build, generate, meter, store."""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai._run_context import RunContext
from pydantic_ai.exceptions import ModelRetry, UserError
from pydantic_ai.messages import BinaryImage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage, RunUsage
from pydantic_ai.workspaces import Workspace
from pydantic_ai_backends import StateBackend

from app.agents.capabilities import get
from app.agents.capabilities._generated import WORKSPACE_OUTPUT_DIR
from app.agents.capabilities._registry import CapabilityBinding
from app.agents.capabilities.budget import (
    BudgetGuard,
    BudgetScope,
    SpendLedger,
    SpendLimit,
    guarded_by,
    metered_by,
)
from app.agents.capabilities.image_generation import ImageGeneration, ImageGenerationConfig
from app.agents.capabilities.image_generation import _toolset as toolset_module
from app.agents.capabilities.image_generation._toolset import (
    build_image_toolset,
    parse_generated_image,
)
from app.agents.capabilities.sandbox._capped import CappedStateBackend
from app.agents.deps import AgentDeps
from app.core.config import settings
from app.core.secret_kinds import ApiKeySecret
from tests.workspaces import ShellFailing, document_workspace

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("generated_media_ledger")]

_IMAGE = BinaryImage(data=b"\x89PNG-bytes", media_type="image/png")


class _FakeResult:
    def __init__(self, output: BinaryImage, usage: RunUsage) -> None:
        self.output = output
        self._usage = usage

    @property
    def usage(self) -> RunUsage:
        # `AgentRunResult.usage` is a property, not a method - the fake matches so
        # a signature drift is caught here rather than in production.
        return self._usage


class _FakeAgent:
    """Stands in for the image subagent so no model is called."""

    raise_exc: Exception | None = None
    last_capabilities: Any = None

    def __init__(self, model: Model, **kwargs: Any) -> None:
        self.model = model
        _FakeAgent.last_capabilities = kwargs.get("capabilities")

    async def run(self, prompt: str) -> _FakeResult:
        if _FakeAgent.raise_exc is not None:
            raise _FakeAgent.raise_exc
        await self.model.request([], None, ModelRequestParameters())
        return _FakeResult(_IMAGE, RunUsage(input_tokens=7, output_tokens=0))


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    # Only the model *run* is faked; `_build_image_model` runs for real (it
    # constructs a provider client with a fake key, no network), so its one
    # branch stays covered.
    monkeypatch.setattr(toolset_module, "PydanticAgent", _FakeAgent)
    build = toolset_module._build_image_model

    def offline_model(model_id: str, api_key: str) -> Model:
        model = build(model_id, api_key)
        monkeypatch.setattr(
            model,
            "request",
            AsyncMock(
                return_value=ModelResponse(
                    parts=[], model_name=model.model_name, usage=RequestUsage(input_tokens=7)
                )
            ),
        )
        return model

    monkeypatch.setattr(toolset_module, "_build_image_model", offline_model)
    _FakeAgent.raise_exc = None


def _ctx(
    organization_id: Any,
    *,
    retry: int = 0,
    max_retries: int = 1,
    workspace: Workspace | None = None,
) -> RunContext[AgentDeps]:
    ctx = RunContext(
        deps=AgentDeps(organization_id=organization_id),
        model=TestModel(),
        usage=RunUsage(),
        retry=retry,
        max_retries=max_retries,
    )
    if workspace is not None:
        ctx.workspace = workspace
    return ctx


async def _generate(toolset: Any, ctx: RunContext[AgentDeps], prompt: str = "a red bicycle") -> str:
    return await toolset.tools["generate_image"].function(ctx, prompt=prompt)


def test_config_leaves_unset_settings_to_the_provider():
    # The default provider is OpenAI, which separates the model that calls the tool
    # from the one that draws - so its `model` is always handed over, and it is the
    # only kwarg an otherwise untouched config carries.
    assert ImageGenerationConfig().to_tool_kwargs() == {"model": "gpt-image-2"}
    assert ImageGenerationConfig(
        provider="google", model="gemini-3-pro-image"
    ).to_tool_kwargs() == ({})
    kwargs = ImageGenerationConfig(quality="high", size="1024x1024").to_tool_kwargs()
    assert kwargs == {"model": "gpt-image-2", "quality": "high", "size": "1024x1024"}


def test_the_builder_reads_the_key_and_the_config():
    definition = get("image_generation")
    binding = CapabilityBinding(
        capability_id="image_generation",
        config={"provider": "google", "model": "gemini-3-pro-image"},
    )
    built = definition.builder(
        _build_context(definition, binding, secret=ApiKeySecret(api_key="sk-image"))
    )
    assert isinstance(built, ImageGeneration)
    assert built.model_id == "google:gemini-3-pro-image"
    assert built.api_key == "sk-image"


async def test_generating_an_image_stores_it_meters_it_and_returns_a_reference():
    organization_id = uuid4()
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}
    )
    ledger = SpendLedger()
    with metered_by(ledger):
        result = await _generate(toolset, _ctx(organization_id))

    image = parse_generated_image(result)
    assert image is not None
    assert image.media_type == "image/png"
    assert image.prompt == "a red bicycle"
    assert image.filename is not None
    assert image.url == f"/api/v1/generated/{image.filename}"
    # The subagent's spend reached the run's ledger - the invisible-spend guard.
    assert [(entry.model_name, entry.input_tokens) for entry in ledger.entries] == [("gpt-5.4", 7)]


async def test_a_generated_image_is_recorded_with_the_conversation_it_was_made_in(
    generated_media_ledger: list[dict[str, object]],
):
    """The record is what deletes the image with its thread, and counts it (#2310)."""
    organization_id, conversation_id = uuid4(), uuid4()
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}
    )
    ctx = _ctx(organization_id)
    ctx.deps.conversation_id = conversation_id

    image = parse_generated_image(await _generate(toolset, ctx))

    assert image is not None
    [row] = generated_media_ledger
    assert row == {
        "organization_id": organization_id,
        "conversation_id": conversation_id,
        "filename": image.filename,
        "storage_path": f"generated_{organization_id}/{image.filename}",
        "size_bytes": len(_IMAGE.data),
    }


async def test_an_organization_past_its_quota_is_told_so_before_anything_is_drawn(
    generated_media_ledger: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
):
    organization_id = uuid4()
    monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 1)
    generated_media_ledger.append({"organization_id": organization_id, "size_bytes": 1024 * 1024})
    _FakeAgent.raise_exc = AssertionError("the image model must not be called")
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}
    )

    answer = await _generate(toolset, _ctx(organization_id))

    assert answer.startswith("Not made: this organization has used its storage")
    # An org administrator cannot raise a deployment setting; the answer names who can.
    assert "operator can raise GENERATED_MEDIA_QUOTA_MB" in answer


async def test_an_image_holds_its_estimate_until_it_is_stored(
    generated_media_ledger: list[dict[str, object]],
    generated_media_reservations: dict[object, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
):
    """Parallel calls in one response are measured against each other through
    what each holds (#2310)."""
    monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 1024)
    held: list[int] = []

    async def watching(self: _FakeAgent, prompt: str) -> _FakeResult:
        held.extend(int(str(c["size_bytes"])) for c in generated_media_reservations.values())
        return _FakeResult(_IMAGE, RunUsage(input_tokens=7, output_tokens=0))

    monkeypatch.setattr(_FakeAgent, "run", watching)
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}
    )

    assert parse_generated_image(await _generate(toolset, _ctx(uuid4()))) is not None

    assert held == [toolset_module.RESERVED_BYTES]
    assert generated_media_reservations == {}
    assert [row["size_bytes"] for row in generated_media_ledger] == [len(_IMAGE.data)]


async def test_an_image_that_was_not_drawn_gives_its_hold_back(
    generated_media_reservations: dict[object, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 1024)
    _FakeAgent.raise_exc = UserError("refused")
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}
    )

    with pytest.raises(ModelRetry):
        await _generate(toolset, _ctx(uuid4()))

    assert generated_media_reservations == {}


async def test_a_quota_of_zero_never_refuses(
    generated_media_ledger: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
):
    organization_id = uuid4()
    monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 0)
    generated_media_ledger.append({"organization_id": organization_id, "size_bytes": 10**12})
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}
    )

    assert parse_generated_image(await _generate(toolset, _ctx(organization_id))) is not None


async def test_a_generated_image_is_also_written_into_an_open_workspace():
    document = StateBackend()
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}
    )
    result = await _generate(toolset, _ctx(uuid4(), workspace=document_workspace(document)))

    image = parse_generated_image(result)
    assert image is not None and image.workspace_path is not None
    assert image.workspace_path.startswith(f"{WORKSPACE_OUTPUT_DIR}/")
    assert document.read_bytes(image.workspace_path) == _IMAGE.data


async def test_a_full_workspace_names_no_path_for_the_image():
    """The image is still stored and linked; a path holding nothing would send the
    model to read it."""
    workspace = document_workspace(CappedStateBackend(max_bytes=10))
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}
    )

    image = parse_generated_image(await _generate(toolset, _ctx(uuid4(), workspace=workspace)))

    assert image is not None and image.url is not None
    assert image.workspace_path is None


async def test_a_container_that_cannot_take_the_image_names_no_path_for_it():
    """A container's shell fails with `WorkspaceError` where a full document
    raises `OSError`; the image was generated and paid for either way."""
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}
    )

    image = parse_generated_image(
        await _generate(toolset, _ctx(uuid4(), workspace=ShellFailing(document_workspace())))
    )

    assert image is not None and image.url is not None
    assert image.workspace_path is None


async def test_without_an_organization_the_image_is_generated_but_not_stored():
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}
    )
    ledger = SpendLedger()
    with metered_by(ledger):
        result = await _generate(toolset, _ctx(None))

    image = parse_generated_image(result)
    assert image is not None
    assert image.filename is None
    assert image.url is None
    # Metered regardless: the money was spent whether or not there was somewhere to keep the file.
    assert len(ledger.entries) == 1


@pytest.mark.security
async def test_a_spent_budget_refuses_an_image_before_reserving_storage(
    generated_media_ledger: list[dict[str, object]],
    generated_media_reservations: dict[object, dict[str, object]],
) -> None:
    guard = BudgetGuard(
        limits=[
            SpendLimit(
                scope=BudgetScope.ORGANIZATION,
                limit_usd=Decimal("1"),
                period_spend=AsyncMock(return_value=Decimal("1")),
            )
        ]
    )
    _FakeAgent.raise_exc = AssertionError("the image provider must not be called")
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}
    )
    with guarded_by(guard):
        result = await _generate(toolset, _ctx(uuid4()))
    assert result == "Not made: this run has spent its budget."
    assert generated_media_ledger == []
    assert generated_media_reservations == {}


async def test_without_a_key_it_refuses_before_spending_or_storing():
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key=None, tool_settings={}
    )
    ledger = SpendLedger()
    with metered_by(ledger), pytest.raises(ModelRetry):
        await _generate(toolset, _ctx(uuid4()))
    assert ledger.entries == []


async def test_a_failing_image_model_asks_the_model_to_retry():
    _FakeAgent.raise_exc = UserError("that prompt was rejected")
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}
    )
    with pytest.raises(ModelRetry, match="Image generation failed"):
        await _generate(toolset, _ctx(uuid4()))


async def test_the_last_attempt_answers_rather_than_ending_the_run():
    """A `ModelRetry` past the tool's budget ends the conversation."""
    _FakeAgent.raise_exc = UserError("that prompt was rejected")
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}
    )

    answered = await _generate(toolset, _ctx(uuid4(), retry=1))

    assert "Image generation failed" in answered


def test_the_capability_builds_its_toolset_once_and_offers_generate_image():
    capability: ImageGeneration = ImageGeneration(model_id="openai-responses:gpt-5.4", api_key="k")
    toolset = capability.get_toolset()

    assert set(toolset.tools) == {"generate_image"}
    assert capability.get_toolset() is toolset


def test_parse_generated_image_rejects_other_results():
    assert parse_generated_image("not json") is None
    assert parse_generated_image('{"kind": "web_search", "query": "x"}') is None


def _build_context(definition: Any, binding: CapabilityBinding, *, secret: Any) -> Any:
    from app.agents.capabilities._registry import CapabilityBuildContext

    return CapabilityBuildContext(
        binding=binding,
        config=definition.validate_config(binding.config),
        resources={},
        secret=secret,
    )
