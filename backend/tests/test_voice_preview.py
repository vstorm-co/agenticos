"""Hearing a draft's voice in the Builder (#54): what is refused, what is cached, what is said."""

import base64
import io
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import anyio
import pytest

from app.agents.spec import VoiceSpec
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.services.voice import preview as preview_module
from app.services.voice.preview import PREVIEW_LINES, VoicePreviewService, as_wav, speak_line

pytestmark = pytest.mark.anyio

_M = "app.services.voice.preview"


def _block(**overrides: object) -> VoiceSpec:
    fields: dict[str, object] = {
        "provider": "openai",
        "model": "gpt-realtime",
        "secret_id": uuid4(),
        "voice": "marin",
    }
    fields.update(overrides)
    return VoiceSpec.model_validate(fields)


class _Redis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ttl: int | None = None) -> bool:
        self.store[key] = value
        return True


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    w = SimpleNamespace(problem=None, secret=MagicMock(), said=[])
    monkeypatch.setattr(
        f"{_M}.provider_keys.key_problem", AsyncMock(side_effect=lambda *a, **kw: w.problem)
    )
    monkeypatch.setattr(
        f"{_M}.OrganizationSecretService.resolve_for_bindings",
        AsyncMock(side_effect=lambda ctx, ids: {} if w.secret is None else {ids[0]: w.secret}),
    )
    monkeypatch.setattr(f"{_M}.build_realtime_model", MagicMock(return_value="model"))
    return w


def _service(world: SimpleNamespace, speak: AsyncMock | None = None):
    redis = _Redis()

    async def default_speak(model: object, line: str) -> tuple[bytes, int]:
        world.said.append(line)
        return b"\x01\x00" * 2400, 24000

    service = VoicePreviewService(MagicMock(), redis, speak=speak or default_speak)
    return service, redis


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(organization_id=uuid4())


async def test_a_voice_is_heard_as_wav_and_cached(world):
    service, redis = _service(world)
    ctx = _ctx()

    audio = await service.preview(ctx, _block(), locale="en")
    again = await service.preview(ctx, _block(), locale="en")

    with wave.open(io.BytesIO(audio)) as file:
        assert (file.getnchannels(), file.getsampwidth(), file.getframerate()) == (1, 2, 24000)
    assert again == audio
    assert world.said == [PREVIEW_LINES["en"]], "the second listen costs nothing"
    assert len(redis.store) == 1


async def test_the_sentence_is_in_the_sections_language_where_one_is_written(world):
    service, _ = _service(world)
    await service.preview(_ctx(), _block(language="pl"), locale="en")
    assert world.said == [PREVIEW_LINES["pl"]]


async def test_another_language_hears_the_consoles_sentence(world):
    service, _ = _service(world)
    await service.preview(_ctx(), _block(language="fr"), locale="de")
    assert world.said == [PREVIEW_LINES["de"]]


@pytest.mark.parametrize(
    "block",
    [
        _block(provider=None),
        _block(secret_id=None),
        _block(model="not-in-the-catalog"),
        _block(provider="nobody"),
    ],
)
async def test_an_unfinished_section_is_refused_before_anything_is_spent(world, block):
    service, _ = _service(world)
    with pytest.raises(BadRequestError) as refused:
        await service.preview(_ctx(), block, locale="en")
    assert refused.value.details == {"reason": "incomplete"}
    assert world.said == []


async def test_a_language_calls_do_not_accept_is_refused_on_its_field(world):
    service, _ = _service(world)
    with pytest.raises(BadRequestError) as refused:
        await service.preview(_ctx(), _block(language="xx"), locale="en")
    assert refused.value.details["fields"][0]["field"] == "language"


async def test_a_key_the_caller_cannot_use_is_refused_on_its_field(world):
    world.problem = "That key is not in this organization's vault"
    service, _ = _service(world)
    with pytest.raises(BadRequestError) as refused:
        await service.preview(_ctx(), _block(), locale="en")
    assert refused.value.details["fields"] == [
        {"field": "secret_id", "message": "That key is not in this organization's vault"}
    ]
    assert world.said == []


async def test_a_key_that_will_not_unseal_is_refused_on_its_field(world):
    world.secret = None
    service, _ = _service(world)
    with pytest.raises(BadRequestError) as refused:
        await service.preview(_ctx(), _block(), locale="en")
    assert refused.value.details["fields"][0]["field"] == "secret_id"


async def test_a_provider_that_does_not_answer_in_time_is_a_timeout(world, monkeypatch):
    monkeypatch.setattr(f"{_M}.PREVIEW_TIMEOUT_SECONDS", 0.01)

    async def hangs(model: object, line: str) -> tuple[bytes, int]:
        await anyio.sleep(1)
        raise AssertionError("unreachable")

    service, redis = _service(world, speak=hangs)
    with pytest.raises(ExternalServiceError) as refused:
        await service.preview(_ctx(), _block(), locale="en")
    assert refused.value.details["reason"] == "timeout"
    assert redis.store == {}


async def test_a_provider_failure_or_silence_is_a_provider_error_and_not_cached(world):
    async def fails(model: object, line: str) -> tuple[bytes, int]:
        raise RuntimeError("401 from the provider, with the key in the URL")

    async def silent(model: object, line: str) -> tuple[bytes, int]:
        return b"", 24000

    for speak in (fails, silent):
        service, redis = _service(world, speak=speak)
        with pytest.raises(ExternalServiceError) as refused:
            await service.preview(_ctx(), _block(), locale="en")
        assert refused.value.details == {
            "reason": "provider_error",
            "provider": "openai",
            "model": "gpt-realtime",
        }
        assert "key" not in refused.value.message
        assert redis.store == {}


async def test_speaking_a_line_collects_every_chunk_until_it_has_played(monkeypatch):
    chunks = [b"\x01\x00", b"\x02\x00", b"\x03\x00"]
    sent: list[str] = []
    played = anyio.Event()

    class Session:
        audio_output_sample_rate = 24000

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        def stream_audio(self):
            async def audio():
                for chunk in chunks:
                    yield chunk
                played.set()
                await anyio.sleep_forever()

            return audio()

        async def send(self, text: str) -> None:
            sent.append(text)

        async def wait_for_reply(self) -> None:
            return None

        async def wait_for_playback(self) -> None:
            await played.wait()

    agent = MagicMock()
    agent.return_value.realtime.return_value.session.return_value = Session()
    monkeypatch.setattr(preview_module, "Agent", agent)

    pcm, rate = await speak_line(MagicMock(), "Hello.")

    assert (pcm, rate) == (b"".join(chunks), 24000)
    assert sent == ["Say exactly: Hello."]


def test_wav_wraps_pcm_without_changing_it():
    audio = as_wav(b"\x10\x00\x20\x00", sample_rate=16000)
    with wave.open(io.BytesIO(audio)) as file:
        assert file.readframes(2) == b"\x10\x00\x20\x00"
    assert base64.b64decode(base64.b64encode(audio)) == audio
