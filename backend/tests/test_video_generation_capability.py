"""The video-generation capability: configure, build, make, meter, store - and refuse.

The provider is never called: `generate_video` is replaced, so these pin what the
tool does around it - the starting image found where the agent left it, the budget
asked with the clip's price before the job, the cost booked by the length made,
the clip kept where an image is kept, and each failure answered by whoever can
fix it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai._run_context import RunContext
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import StateBackend

from app.agents.capabilities import get
from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext
from app.agents.capabilities.budget import (
    BudgetGuard,
    BudgetScope,
    SpendLedger,
    SpendLimit,
    guarded_by,
    metered_by,
)
from app.agents.capabilities.video_generation import VideoGeneration, VideoGenerationConfig
from app.agents.capabilities.video_generation import _toolset as toolset_module
from app.agents.capabilities.video_generation._toolset import (
    VideoSettings,
    build_video_toolset,
    parse_generated_video,
)
from app.agents.deps import AgentDeps
from app.core.config import settings
from app.core.secret_kinds import ApiKeySecret
from app.services import video_models
from app.services.generated_media import save_generated_media
from app.services.video_generation import Clip, VideoFailure, VideoProviderError
from tests.workspaces import ShellFailing, document_workspace

pytestmark = pytest.mark.anyio

MP4 = b"\x00\x00\x00\x20ftypisom"


class _FakeGeneration:
    """Stands in for `generate_video`, recording what it was asked."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: VideoProviderError | None = None
        self.seconds: float | None = 5.0

    async def __call__(self, provider: Any, **kwargs: Any) -> Clip:
        self.calls.append({"provider": provider.provider, **kwargs})
        if self.error is not None:
            raise self.error
        return Clip(data=MP4, seconds=self.seconds)


@pytest.fixture
def generation(monkeypatch: pytest.MonkeyPatch, tmp_path) -> _FakeGeneration:
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    fake = _FakeGeneration()
    monkeypatch.setattr(toolset_module, "generate_video", fake)
    return fake


def _ctx(
    organization_id: Any = None, *, retry: int = 0, workspace: Any = None
) -> RunContext[AgentDeps]:
    ctx = RunContext(
        deps=AgentDeps(organization_id=organization_id),
        model=TestModel(),
        usage=RunUsage(),
        retry=retry,
        max_retries=1,
    )
    if workspace is not None:
        ctx.workspace = workspace
    return ctx


def _settings(**overrides: Any) -> VideoSettings:
    base = {
        "provider": "byteplus",
        "model": "dreamina-seedance-2-0-260128",
        "resolution": "720p",
        "aspect_ratio": "16:9",
        "seconds": 5,
        "max_seconds": 10,
        "audio": True,
        "timeout_seconds": 600,
    }
    return VideoSettings(**{**base, **overrides})


def _toolset(api_key: str | None = "sk-video", **overrides: Any) -> Any:
    return build_video_toolset(_settings(**overrides), api_key=api_key)


async def _make(
    toolset: Any, ctx: RunContext[AgentDeps], prompt: str = "A red bicycle.", **kw: Any
) -> str:
    return await toolset.tools["generate_video"].function(ctx, prompt=prompt, **kw)


def _price(provider: str, model: str, resolution: str) -> Decimal:
    entry = video_models.by_provider(provider)
    assert entry is not None
    chosen = entry.model(model)
    assert chosen is not None
    price = video_models.price_per_second(chosen, resolution, on=datetime.now(UTC).date())
    assert price is not None
    return price


class TestConfiguration:
    def test_turning_it_on_is_enough_to_make_a_clip(self):
        config = VideoGenerationConfig()

        assert (config.provider, config.model) == video_models.default_choice()

    @pytest.mark.parametrize(
        ("config", "says"),
        [
            ({"provider": "xai", "model": "grok-9"}, "cannot make video"),
            ({"provider": "xai", "model": "grok-imagine-video-1.5", "resolution": "4k"}, "not 4k"),
            (
                {"provider": "xai", "model": "grok-imagine-video-1.5", "aspect_ratio": "5:4"},
                "not 5:4",
            ),
            (
                {"provider": "xai", "model": "grok-imagine-video-1.5", "seconds": 16},
                "seconds cannot be 16",
            ),
            (
                {"provider": "xai", "model": "grok-imagine-video-1.5", "max_seconds": 20},
                "max_seconds cannot be 20",
            ),
            (
                {
                    "provider": "xai",
                    "model": "grok-imagine-video-1.5",
                    "seconds": 9,
                    "max_seconds": 6,
                },
                "cannot be longer",
            ),
        ],
        ids=["model", "resolution", "aspect ratio", "length", "longest", "usual over longest"],
    )
    def test_a_choice_the_provider_would_refuse_is_refused_here(self, config, says):
        with pytest.raises(ValidationError, match=says):
            VideoGenerationConfig(**config)

    def test_a_model_dropped_after_validation_is_said_rather_than_guessed(self, monkeypatch):
        config = VideoGenerationConfig()
        monkeypatch.setattr(video_models, "CATALOG", ())

        with pytest.raises(ValueError, match="no longer offered"):
            config.chosen_model()


def test_the_key_picker_narrows_to_the_chosen_provider():
    requirement = get("video_generation").secret
    assert requirement is not None and requirement.required_when is not None
    assert requirement.required_when.field == "provider"
    assert set(requirement.required_when.equals) == {
        entry.provider for entry in video_models.providers()
    }


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({"provider": "xai", "model": "grok-imagine-video-1.5"}, ("720p", "16:9", 5, 15)),
        (
            {
                "provider": "byteplus",
                "model": "dreamina-seedance-2-5-260628",
                "resolution": "1080p",
                "seconds": 8,
                "max_seconds": 12,
            },
            ("1080p", "16:9", 8, 12),
        ),
        ({"provider": "google", "model": "gemini-omni-1.1-flash"}, ("720p", "16:9", 5, 10)),
    ],
    ids=["defaults", "chosen", "nearest usual length"],
)
def test_the_builder_resolves_the_defaults_from_the_model(config, expected):
    definition = get("video_generation")
    binding = CapabilityBinding(capability_id="video_generation", config=config)
    built = definition.builder(
        CapabilityBuildContext(
            binding=binding,
            config=definition.validate_config(binding.config),
            resources={},
            secret=ApiKeySecret(api_key="sk-video"),
        )
    )

    assert isinstance(built, VideoGeneration)
    assert (built.resolution, built.aspect_ratio, built.seconds, built.max_seconds) == expected
    assert built.api_key == "sk-video" and "sk-video" not in repr(built)


def test_without_a_config_or_key_it_builds_on_the_defaults():
    definition = get("video_generation")
    built = definition.builder(
        CapabilityBuildContext(
            binding=CapabilityBinding(capability_id="video_generation", config={}),
            config=None,
            resources={},
            secret=None,
        )
    )

    assert isinstance(built, VideoGeneration) and built.api_key is None


def test_the_capability_builds_its_toolset_once_and_offers_generate_video():
    capability = VideoGeneration(
        provider="xai",
        model="grok-imagine-video-1.5",
        resolution="720p",
        aspect_ratio="16:9",
        seconds=5,
        max_seconds=15,
        audio=None,
        timeout_seconds=600,
    )

    toolset = capability.get_toolset()

    assert capability.get_toolset() is toolset
    assert list(toolset.tools) == ["generate_video"]


class TestMaking:
    async def test_stores_the_clip_meters_its_length_and_returns_a_reference(self, generation):
        generation.seconds = 6.0
        ledger = SpendLedger()
        with metered_by(ledger):
            result = await _make(_toolset(), _ctx(uuid4()), seconds=6, aspect_ratio="9:16")

        video = parse_generated_video(result)
        assert video is not None
        assert video.media_type == "video/mp4" and video.seconds == 6.0
        assert video.filename is not None and video.filename.endswith("_video.mp4")
        assert video.url == f"/api/v1/generated/{video.filename}"
        [call] = generation.calls
        assert (call["duration"], call["aspect_ratio"], call["audio"], call["api_key"]) == (
            6,
            "9:16",
            True,
            "sk-video",
        )
        [entry] = ledger.entries
        assert entry.model_name == "byteplus:dreamina-seedance-2-0-260128"
        assert entry.cost_usd == _price("byteplus", "dreamina-seedance-2-0-260128", "720p") * 6

    async def test_a_length_the_provider_does_not_report_is_booked_as_asked(self, generation):
        generation.seconds = None
        ledger = SpendLedger()
        with metered_by(ledger):
            await _make(_toolset(), _ctx(uuid4()))

        assert (
            ledger.entries[0].cost_usd
            == _price("byteplus", "dreamina-seedance-2-0-260128", "720p") * 5
        )

    async def test_a_model_that_decides_its_own_length_is_sent_none_and_priced_at_its_longest(
        self, generation
    ):
        generation.seconds = None
        ledger = SpendLedger()
        toolset = _toolset(provider="google", model="gemini-omni-1.1-flash")
        with metered_by(ledger):
            await _make(toolset, _ctx(uuid4()), seconds=3)

        assert generation.calls[0]["duration"] is None
        assert ledger.entries[0].cost_usd == _price("google", "gemini-omni-1.1-flash", "720p") * 10

    async def test_the_clip_is_also_written_into_an_open_workspace(self, generation):
        document = StateBackend()
        result = await _make(_toolset(), _ctx(uuid4(), workspace=document_workspace(document)))

        video = parse_generated_video(result)
        assert video is not None and video.workspace_path is not None
        assert document.read_bytes(video.workspace_path) == MP4

    async def test_without_an_organization_the_clip_is_made_but_not_stored(self, generation):
        video = parse_generated_video(await _make(_toolset(), _ctx(None)))

        assert video is not None and (video.filename, video.url) == (None, None)

    async def test_an_unpriced_clip_is_made_and_booked_as_unpriced(self, generation, monkeypatch):
        monkeypatch.setattr(toolset_module, "price_per_second", lambda *_a, **_k: None)
        ledger = SpendLedger()
        with metered_by(ledger):
            await _make(_toolset(), _ctx(uuid4()))

        assert ledger.has_unpriced_models is True


class TestStartingFromAnImage:
    async def test_an_image_this_organization_generated_is_found_by_its_filename(
        self, generation, tmp_path
    ):
        organization_id = uuid4()
        leaf = await save_generated_media(organization_id, b"\x89PNG-logo", filename="image.png")

        await _make(_toolset(), _ctx(organization_id), first_frame=leaf)

        frame = generation.calls[0]["first_frame"]
        assert (frame.data, frame.mime_type) == (b"\x89PNG-logo", "image/png")

    async def test_a_workspace_path_is_read_from_the_workspace(self, generation):
        document = StateBackend()
        document.write_bytes("output/logo.jpg", b"jpeg-logo")

        await _make(
            _toolset(),
            _ctx(uuid4(), workspace=document_workspace(document)),
            first_frame="output/logo.jpg",
        )

        frame = generation.calls[0]["first_frame"]
        assert (frame.data, frame.mime_type) == (b"jpeg-logo", "image/jpeg")

    async def test_a_leaf_not_generated_here_is_looked_for_in_the_workspace(self, generation):
        document = StateBackend()
        document.write_bytes("logo.webp", b"webp-logo")

        await _make(
            _toolset(),
            _ctx(uuid4(), workspace=document_workspace(document)),
            first_frame="logo.webp",
        )

        assert generation.calls[0]["first_frame"].mime_type == "image/webp"

    @pytest.mark.parametrize(
        ("source", "workspace", "says"),
        [
            ("clip.gif", None, "PNG, JPEG or WebP"),
            (
                "missing.png",
                None,
                "There is no image called 'missing.png' among the files generated here.",
            ),
            ("missing.png", "document", "or in your workspace"),
            ("missing.png", "failing", "or in your workspace"),
        ],
        ids=["format", "nowhere", "not in the workspace", "a workspace that cannot read"],
    )
    async def test_an_image_that_cannot_be_used_is_steered(
        self, generation, source, workspace, says
    ):
        ctx_workspace = {
            None: None,
            "document": document_workspace(StateBackend()),
            "failing": ShellFailing(document_workspace()),
        }[workspace]

        with pytest.raises(ModelRetry, match=says):
            await _make(_toolset(), _ctx(uuid4(), workspace=ctx_workspace), first_frame=source)
        assert generation.calls == []

    async def test_an_image_too_large_to_send_is_steered(self, generation, monkeypatch):
        monkeypatch.setattr(toolset_module, "MAX_FRAME_BYTES", 2)
        organization_id = uuid4()
        leaf = await save_generated_media(organization_id, b"\x89PNG-logo", filename="image.png")

        with pytest.raises(ModelRetry, match="larger than"):
            await _make(_toolset(), _ctx(organization_id), first_frame=leaf)

    async def test_a_model_that_cannot_start_from_an_image_is_steered(
        self, generation, monkeypatch
    ):
        from dataclasses import replace

        entry = video_models.CATALOG[1]
        models = tuple(replace(model, first_frame=False) for model in entry.models)
        monkeypatch.setattr(video_models, "CATALOG", (replace(entry, models=models),))

        with pytest.raises(ModelRetry, match="cannot start from an image"):
            await _make(_toolset(), _ctx(uuid4()), first_frame="logo.png")


@pytest.mark.security
class TestRefusingBeforeSubmitting:
    async def test_without_a_key(self, generation):
        with pytest.raises(ModelRetry, match="no API key"):
            await _make(_toolset(api_key=None), _ctx(uuid4()))

    async def test_a_blank_prompt(self, generation):
        with pytest.raises(ModelRetry, match="empty"):
            await _make(_toolset(), _ctx(uuid4()), "  ")

    async def test_a_length_past_the_agents_limit_names_the_range(self, generation):
        with pytest.raises(ModelRetry, match="must be 4 to 10"):
            await _make(_toolset(), _ctx(uuid4()), seconds=11)
        assert generation.calls == []

    async def test_a_shape_the_model_does_not_render(self, generation):
        with pytest.raises(ModelRetry, match="must be one of"):
            await _make(_toolset(), _ctx(uuid4()), aspect_ratio="5:4")

    async def test_on_the_last_attempt_the_steer_is_the_answer(self, generation):
        assert "empty" in await _make(_toolset(), _ctx(uuid4(), retry=1), " ")

    async def test_a_model_the_catalog_has_since_dropped(self, generation, monkeypatch):
        monkeypatch.setattr(video_models, "CATALOG", ())

        result = await _make(_toolset(), _ctx(uuid4()))

        assert result.startswith("Not made: this agent's video model is no longer offered")

    async def test_a_clip_that_would_pass_the_cap_is_refused_with_its_price(self, generation):
        price = _price("byteplus", "dreamina-seedance-2-0-260128", "720p")
        guard = BudgetGuard(
            ledger=SpendLedger(), limits=[SpendLimit(scope=BudgetScope.AGENT, limit_usd=price * 4)]
        )
        with guarded_by(guard):
            result = await _make(_toolset(), _ctx(uuid4()))

        assert result == (
            f"Not made: this clip would cost about ${price * 5:.2f}, more than the budget this run has left."
        )
        assert generation.calls == []

    async def test_an_unpriced_clip_is_refused_once_the_budget_is_spent(
        self, generation, monkeypatch
    ):
        monkeypatch.setattr(toolset_module, "price_per_second", lambda *_a, **_k: None)
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[SpendLimit(scope=BudgetScope.ORGANIZATION, limit_usd=Decimal(0))],
        )
        with guarded_by(guard):
            result = await _make(_toolset(), _ctx(uuid4()))

        assert result == "Not made: this run has spent its budget."


class TestAFailedJob:
    @pytest.mark.parametrize(
        ("failure", "answer"),
        [
            (VideoFailure.CREDENTIALS, "refused this agent's API key"),
            (VideoFailure.TIMED_OUT, "not ready within 600 seconds"),
        ],
    )
    async def test_what_the_model_cannot_fix_is_answered_not_retried(
        self, generation, failure, answer
    ):
        generation.error = VideoProviderError(failure, provider="byteplus")
        ledger = SpendLedger()
        with metered_by(ledger):
            result = await _make(_toolset(), _ctx(uuid4()))

        assert result.startswith("Not made:") and answer in result
        assert ledger.entries == []

    async def test_a_policy_refusal_asks_for_a_different_shot(self, generation):
        generation.error = VideoProviderError(VideoFailure.POLICY, provider="byteplus")

        with pytest.raises(ModelRetry, match="Describe the shot differently"):
            await _make(_toolset(), _ctx(uuid4()))

    @pytest.mark.parametrize(
        "failure", [VideoFailure.REJECTED, VideoFailure.RATE_LIMITED, VideoFailure.UNAVAILABLE]
    )
    async def test_a_transient_or_refused_request_is_worth_one_more_try(self, generation, failure):
        generation.error = VideoProviderError(failure, provider="byteplus")

        with pytest.raises(ModelRetry, match="Try once more"):
            await _make(_toolset(), _ctx(uuid4()))


def test_parse_generated_video_rejects_other_results():
    assert parse_generated_video("Not made: no.") is None
    assert (
        parse_generated_video(
            '{"kind": "generated_speech", "voice": "x", "characters": 1, "media_type": "a"}'
        )
        is None
    )
