"""The image generation capability: build, generate, meter, store."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from pydantic_ai._run_context import RunContext
from pydantic_ai.exceptions import ModelRetry, UserError
from pydantic_ai.messages import BinaryImage
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import StateBackend, ensure_async

from app.agents.capabilities import get
from app.agents.capabilities._registry import CapabilityBinding
from app.agents.capabilities.budget import SpendLedger, metered_by
from app.agents.capabilities.image_generation import ImageGeneration, ImageGenerationConfig
from app.agents.capabilities.image_generation import _toolset as toolset_module
from app.agents.capabilities.image_generation._toolset import (
    WORKSPACE_OUTPUT_DIR,
    build_image_toolset,
    parse_generated_image,
)
from app.agents.deps import AgentDeps
from app.core.config import settings
from app.core.secret_kinds import ApiKeySecret

pytestmark = pytest.mark.anyio

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

    def __init__(self, model: Any, **kwargs: Any) -> None:
        _FakeAgent.last_capabilities = kwargs.get("capabilities")

    async def run(self, prompt: str) -> _FakeResult:
        if _FakeAgent.raise_exc is not None:
            raise _FakeAgent.raise_exc
        return _FakeResult(_IMAGE, RunUsage(input_tokens=7, output_tokens=0))


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    # Only the model *run* is faked; `_build_image_model` runs for real (it
    # constructs a provider client with a fake key, no network), so its one
    # branch stays covered.
    monkeypatch.setattr(toolset_module, "PydanticAgent", _FakeAgent)
    _FakeAgent.raise_exc = None


def _ctx(organization_id: Any) -> RunContext[AgentDeps]:
    return RunContext(
        deps=AgentDeps(organization_id=organization_id),
        model=TestModel(),
        usage=RunUsage(),
    )


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
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}, workspace_backend=None
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


async def test_a_generated_image_is_also_written_into_an_open_workspace():
    backend = StateBackend()
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4",
        api_key="k",
        tool_settings={},
        workspace_backend=backend,
    )
    result = await _generate(toolset, _ctx(uuid4()))

    image = parse_generated_image(result)
    assert image is not None and image.workspace_path is not None
    assert image.workspace_path.startswith(f"{WORKSPACE_OUTPUT_DIR}/")
    assert await ensure_async(backend).read_bytes(image.workspace_path) == _IMAGE.data


async def test_without_an_organization_the_image_is_generated_but_not_stored():
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}, workspace_backend=None
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


async def test_without_a_key_it_refuses_before_spending_or_storing():
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key=None, tool_settings={}, workspace_backend=None
    )
    ledger = SpendLedger()
    with metered_by(ledger), pytest.raises(ModelRetry):
        await _generate(toolset, _ctx(uuid4()))
    assert ledger.entries == []


async def test_a_failing_image_model_asks_the_model_to_retry():
    _FakeAgent.raise_exc = UserError("that prompt was rejected")
    toolset = build_image_toolset(
        model_id="openai-responses:gpt-5.4", api_key="k", tool_settings={}, workspace_backend=None
    )
    with pytest.raises(ModelRetry, match="Image generation failed"):
        await _generate(toolset, _ctx(uuid4()))


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
