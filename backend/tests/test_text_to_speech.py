"""Speaking text through each provider, and what a failed call is allowed to say.

Every provider is answered by a `MockTransport`, so these pin the request each one
is sent - the key in a header and nowhere else, the voice where the provider reads
it - and what is made of the answer: one clip however many requests it took, and a
refusal that never carries the provider's own words.
"""

import base64
import json
import logging
import struct
from collections.abc import Callable, Generator
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

from app.services.text_to_speech import SpeechFailure, SpeechProviderError, SpokenPiece, synthesize
from app.services.text_to_speech import synthesis as module
from app.services.text_to_speech.synthesis import split_text, wav
from app.services.text_to_speech_models import TextToSpeechProvider, by_provider

pytestmark = pytest.mark.anyio

KEY = "sk-speech-secret"


def _provider(provider_id: str) -> TextToSpeechProvider:
    entry = by_provider(provider_id)
    assert entry is not None
    return entry


@contextmanager
def _answering(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Generator[list[httpx.Request]]:
    """Every request the synthesis makes, answered by `handler` and recorded."""
    seen: list[httpx.Request] = []
    real = httpx.AsyncClient

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(record)
        return real(*args, **kwargs)

    with patch.object(module.httpx, "AsyncClient", client):
        yield seen


def _gemini_answer(pcm: bytes) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "steps": [
                {"type": "thought", "content": []},
                {
                    "type": "model_output",
                    "content": [{"type": "audio", "data": base64.b64encode(pcm).decode()}],
                },
            ]
        },
    )


class TestEachProvidersRequest:
    async def test_openai_is_sent_the_text_voice_format_and_direction(self):
        with _answering(lambda _: httpx.Response(200, content=b"ID3-mp3")) as seen:
            speech = await synthesize(
                _provider("openai"),
                model="gpt-4o-mini-tts",
                voice="marin",
                text="Dzień dobry.",
                audio_format="mp3",
                api_key=KEY,
                instructions="Calm and slow.",
            )

        [request] = seen
        assert str(request.url) == "https://api.openai.com/v1/audio/speech"
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert json.loads(request.content) == {
            "model": "gpt-4o-mini-tts",
            "input": "Dzień dobry.",
            "voice": "marin",
            "response_format": "mp3",
            "instructions": "Calm and slow.",
        }
        assert speech.data == b"ID3-mp3"
        assert (speech.audio_format, speech.characters, speech.requests) == ("mp3", 12, 1)

    async def test_a_model_that_reads_no_direction_is_not_sent_one(self):
        """`tts-1` refuses `instructions`; sending it would fail every call."""
        with _answering(lambda _: httpx.Response(200, content=b"mp3")) as seen:
            await synthesize(
                _provider("openai"),
                model="tts-1",
                voice="alloy",
                text="Hello.",
                audio_format="mp3",
                api_key=KEY,
                instructions="Whisper.",
            )

        assert "instructions" not in json.loads(seen[0].content)

    async def test_elevenlabs_reads_the_voice_from_the_path_and_the_key_from_its_header(self):
        with _answering(lambda _: httpx.Response(200, content=b"mp3")) as seen:
            await synthesize(
                _provider("elevenlabs"),
                model="eleven_multilingual_v2",
                voice="JBFqnCBsd6RMkjVDRZzb",
                text="Hello.",
                audio_format="mp3",
                api_key=KEY,
            )

        [request] = seen
        assert request.url.path == "/v1/text-to-speech/JBFqnCBsd6RMkjVDRZzb"
        assert request.url.params["output_format"] == "mp3_44100_128"
        assert request.headers["xi-api-key"] == KEY
        assert "authorization" not in request.headers
        assert KEY not in str(request.url)
        assert json.loads(request.content) == {
            "text": "Hello.",
            "model_id": "eleven_multilingual_v2",
        }

    @pytest.mark.parametrize("voice", ["../../user", ".", "..", "a/b", ""])
    async def test_an_elevenlabs_voice_id_cannot_reach_another_endpoint(self, voice):
        """The id comes from a binding's configuration and lands in the path, where
        `.` and `..` would be resolved away and send the key elsewhere."""
        with (
            _answering(lambda _: httpx.Response(200, content=b"mp3")) as seen,
            pytest.raises(ValueError),
        ):
            await synthesize(
                _provider("elevenlabs"),
                model="eleven_multilingual_v2",
                voice=voice,
                text="Hello.",
                audio_format="mp3",
                api_key=KEY,
            )

        assert seen == []

    async def test_gemini_is_asked_for_pcm_and_given_the_direction_as_a_style(self):
        with _answering(lambda _: _gemini_answer(b"\x01\x00\x02\x00")) as seen:
            speech = await synthesize(
                _provider("google"),
                model="gemini-3.8-flash-tts",
                voice="Kore",
                text="Cześć!",
                audio_format="wav",
                api_key=KEY,
                instructions="cheerful",
            )

        [request] = seen
        assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/interactions"
        assert request.headers["x-goog-api-key"] == KEY
        body = json.loads(request.content)
        assert body["model"] == "gemini-3.8-flash-tts"
        assert body["input"][0]["content"][0]["annotations"] == [
            {"type": "speech_metadata", "style": "cheerful"}
        ]
        assert body["response_format"]["mime_type"] == "audio/l16"
        assert body["generation_config"] == {"speech_config": [{"voice": "Kore"}]}
        assert speech.data == wav(b"\x01\x00\x02\x00")

    async def test_gemini_without_a_direction_sends_plain_text(self):
        with _answering(lambda _: _gemini_answer(b"\x00\x00")) as seen:
            await synthesize(
                _provider("google"),
                model="gemini-3.8-flash-tts",
                voice="Kore",
                text="Hi.",
                audio_format="wav",
                api_key=KEY,
            )

        assert json.loads(seen[0].content)["input"][0]["content"][0] == {
            "type": "text",
            "text": "Hi.",
        }

    @pytest.mark.parametrize(
        "body",
        [
            {"steps": []},
            {"steps": [{"type": "model_output", "content": [{"type": "audio", "data": "*"}]}]},
            [],
        ],
        ids=["no audio", "not base64", "not an object"],
    )
    async def test_a_gemini_answer_with_no_audio_is_unavailable(self, body: object):
        with (
            _answering(lambda _: httpx.Response(200, json=body)),
            pytest.raises(SpeechProviderError) as caught,
        ):
            await synthesize(
                _provider("google"),
                model="gemini-3.8-flash-tts",
                voice="Kore",
                text="Hi.",
                audio_format="wav",
                api_key=KEY,
            )

        assert caught.value.failure is SpeechFailure.UNAVAILABLE


class TestALongText:
    async def test_is_spoken_in_pieces_and_joined_into_one_wav(self):
        """Two WAV files back to back are not one WAV file, so each piece is asked
        for as PCM and one header is written around all of it."""
        pcm_pieces = iter([b"\x01\x00", b"\x02\x00", b"\x03\x00"])
        with _answering(lambda _: httpx.Response(200, content=next(pcm_pieces))) as seen:
            speech = await synthesize(
                _provider("openai"),
                model="gpt-4o-mini-tts",
                voice="marin",
                text=("Pierwsze zdanie tekstu. " * 300).strip(),
                audio_format="wav",
                api_key=KEY,
            )

        assert len(seen) == speech.requests == 2
        assert all(json.loads(request.content)["response_format"] == "pcm" for request in seen)
        assert speech.data == wav(b"\x01\x00\x02\x00")

    async def test_mp3_pieces_are_concatenated(self):
        with _answering(lambda request: httpx.Response(200, content=b"frame")) as seen:
            speech = await synthesize(
                _provider("elevenlabs"),
                model="eleven_multilingual_v2",
                voice="v",
                text="word " * 2500,
                audio_format="mp3",
                api_key=KEY,
            )

        assert speech.data == b"frame" * len(seen)
        assert len(seen) == 2

    def test_is_cut_where_speech_pauses(self):
        text = "First sentence here. Second sentence here. Third one."

        assert split_text(text, 45) == ["First sentence here. Second sentence here.", "Third one."]

    def test_a_paragraph_break_is_preferred_to_a_sentence(self):
        text = "One. Two.\n\nThree. Four."

        assert split_text(text, 20) == ["One. Two.", "Three. Four."]

    def test_a_word_longer_than_the_limit_is_cut_rather_than_refused(self):
        assert split_text("x" * 25, 10) == ["x" * 10, "x" * 10, "x" * 5]

    def test_chinese_and_japanese_are_cut_after_a_sentence(self):
        """They end a sentence with no space after it, so the ASCII marks never match."""
        assert split_text("这是一个句子。" * 3, 15) == [
            "这是一个句子。这是一个句子。",
            "这是一个句子。",
        ]

    async def test_mp3_pieces_after_the_first_lose_their_id3_tag(self):
        tag = b"ID3\x04\x00\x00\x00\x00\x00\x02ab"
        pieces = iter([tag + b"frame1", tag + b"frame2"])
        with _answering(lambda _: httpx.Response(200, content=next(pieces))):
            speech = await synthesize(
                _provider("elevenlabs"),
                model="eleven_multilingual_v2",
                voice="v",
                text="word " * 2500,
                audio_format="mp3",
                api_key=KEY,
            )

        assert speech.data == tag + b"frame1" + b"frame2"

    def test_text_within_the_limit_is_one_piece(self):
        assert split_text("  Short.  ", 100) == ["Short."]


class TestAFailedCall:
    @pytest.mark.parametrize(
        ("status", "body", "failure"),
        [
            (
                400,
                '{"error":{"details":[{"reason":"API_KEY_INVALID"}]}}',
                SpeechFailure.CREDENTIALS,
            ),
            (401, '{"detail":{"status":"quota_exceeded"}}', SpeechFailure.RATE_LIMITED),
            (408, "slow", SpeechFailure.UNAVAILABLE),
            (400, '{"detail":{"status":"voice_not_found"}}', SpeechFailure.NOT_FOUND),
            (402, '{"detail":{"status":"paid_plan_required"}}', SpeechFailure.CREDENTIALS),
        ],
        ids=["gemini bad key", "elevenlabs quota", "request timeout", "voice gone", "plan lacking"],
    )
    async def test_the_providers_reason_outranks_its_status(self, status, body, failure):
        """Gemini answers a bad key 400 and ElevenLabs a spent quota 401; by status
        alone the model would rephrase fine text and the operator replace a working key."""
        with (
            _answering(lambda _: httpx.Response(status, text=body)),
            pytest.raises(SpeechProviderError) as caught,
        ):
            await synthesize(
                _provider("openai"),
                model="gpt-4o-mini-tts",
                voice="marin",
                text="Hello.",
                audio_format="mp3",
                api_key=KEY,
            )

        assert caught.value.failure is failure

    @pytest.mark.parametrize(
        ("body", "audio_format"), [(b"", "mp3"), (b"\x01\x00\x02", "wav")], ids=["empty", "odd PCM"]
    )
    async def test_an_answer_that_cannot_be_a_clip_is_unavailable(self, body, audio_format):
        with (
            _answering(lambda _: httpx.Response(200, content=body)),
            pytest.raises(SpeechProviderError) as caught,
        ):
            await synthesize(
                _provider("openai"),
                model="gpt-4o-mini-tts",
                voice="marin",
                text="Hello.",
                audio_format=audio_format,
                api_key=KEY,
            )

        assert caught.value.failure is SpeechFailure.UNAVAILABLE

    @pytest.mark.parametrize(
        ("status", "failure"),
        [
            (401, SpeechFailure.CREDENTIALS),
            (403, SpeechFailure.CREDENTIALS),
            (404, SpeechFailure.NOT_FOUND),
            (422, SpeechFailure.REJECTED),
            (429, SpeechFailure.RATE_LIMITED),
            (500, SpeechFailure.UNAVAILABLE),
        ],
    )
    async def test_says_what_went_wrong_and_not_what_the_provider_said(self, status, failure):
        leaked = f"invalid key {KEY} for https://api.example/?key={KEY}"
        with (
            _answering(lambda _: httpx.Response(status, text=leaked)),
            pytest.raises(SpeechProviderError) as caught,
        ):
            await synthesize(
                _provider("openai"),
                model="gpt-4o-mini-tts",
                voice="marin",
                text="Hello.",
                audio_format="mp3",
                api_key=KEY,
            )

        assert caught.value.failure is failure
        assert caught.value.details == {
            "provider": "openai",
            "failure": failure.value,
            "status": status,
        }
        assert KEY not in caught.value.message
        assert KEY not in json.dumps(caught.value.details)

    @pytest.mark.parametrize(
        ("body", "logged"),
        [
            (
                f'{{"error":{{"code":"invalid_api_key","message":"{KEY} is wrong"}}}}',
                "invalid_api_key",
            ),
            ('{"error":{"code":400,"status":"INVALID_ARGUMENT"}}', "INVALID_ARGUMENT"),
            ('{"detail":{"status":"voice_not_found","message":"Say: hello"}}', "voice_not_found"),
            (f'{{"error":{{"code":"key {KEY} refused"}}}}', "no error code"),
            (f"invalid key {KEY}", "no error code"),
            ("[1, 2]", "no error code"),
        ],
        ids=[
            "openai",
            "gemini",
            "elevenlabs",
            "a sentence for a code",
            "not json",
            "not an object",
        ],
    )
    async def test_only_the_providers_error_code_is_logged(self, caplog, body, logged):
        """A body may echo the key or the words sent; the code is all the operator
        needs, and anything not shaped like one is left out."""
        with (
            caplog.at_level(logging.WARNING),
            _answering(lambda _: httpx.Response(400, text=body)),
            pytest.raises(SpeechProviderError),
        ):
            await synthesize(
                _provider("openai"),
                model="gpt-4o-mini-tts",
                voice="marin",
                text="Say: hello",
                audio_format="mp3",
                api_key=KEY,
            )

        assert caplog.records[-1].getMessage().endswith(f"failed (400): {logged}")
        assert KEY not in caplog.text and "Say: hello" not in caplog.text

    async def test_each_piece_is_reported_as_soon_as_it_is_spoken(self):
        """The clip is discarded on a failure; what the first piece cost is not, and
        the caller has already been told of it."""
        spoken: list[SpokenPiece] = []
        answers = iter([httpx.Response(200, content=b"\x01\x00"), httpx.Response(500)])
        with _answering(lambda _: next(answers)), pytest.raises(SpeechProviderError):
            await synthesize(
                _provider("openai"),
                model="gpt-4o-mini-tts",
                voice="marin",
                text="word " * 1000,
                audio_format="wav",
                api_key=KEY,
                on_spoken=spoken.append,
            )

        first_piece = split_text(("word " * 1000).strip(), 4096)[0]
        # Two bytes of 16-bit PCM at 24 kHz: one sample, and its length is known.
        assert spoken == [SpokenPiece(characters=len(first_piece), seconds=1 / 24_000)]

    async def test_a_timeout_is_unavailable(self):
        def time_out(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        with _answering(time_out), pytest.raises(SpeechProviderError) as caught:
            await synthesize(
                _provider("openai"),
                model="gpt-4o-mini-tts",
                voice="marin",
                text="Hello.",
                audio_format="mp3",
                api_key=KEY,
            )

        assert caught.value.failure is SpeechFailure.UNAVAILABLE
        assert caught.value.details == {
            "provider": "openai",
            "failure": "unavailable",
            "status": None,
        }


class TestWhatTheCallerMustRefuseFirst:
    @pytest.mark.parametrize(
        ("provider", "model", "audio_format"),
        [("google", "gemini-3.8-flash-tts", "mp3"), ("openai", "tts-imaginary", "mp3")],
        ids=["a format the provider does not return", "a model the catalog does not list"],
    )
    async def test_an_unoffered_configuration_is_refused_before_any_request(
        self, provider, model, audio_format
    ):
        with _answering(lambda _: httpx.Response(200)) as seen, pytest.raises(ValueError):
            await synthesize(
                _provider(provider),
                model=model,
                voice="Kore",
                text="Hi.",
                audio_format=audio_format,
                api_key=KEY,
            )

        assert seen == []

    async def test_a_voice_the_model_does_not_speak_in_is_refused_before_any_request(self):
        """`tts-1` speaks in nine of OpenAI's voices, and `marin` is not one of them."""
        with _answering(lambda _: httpx.Response(200)) as seen, pytest.raises(ValueError):
            await synthesize(
                _provider("openai"),
                model="tts-1",
                voice="marin",
                text="Hi.",
                audio_format="mp3",
                api_key=KEY,
            )

        assert seen == []

    async def test_blank_text_is_refused_before_any_request(self):
        with _answering(lambda _: httpx.Response(200)) as seen, pytest.raises(ValueError):
            await synthesize(
                _provider("openai"),
                model="gpt-4o-mini-tts",
                voice="marin",
                text="   ",
                audio_format="mp3",
                api_key=KEY,
            )

        assert seen == []


def test_the_wav_header_describes_24khz_mono_16_bit_pcm():
    header = wav(b"\x00" * 8)[:44]

    riff, size, wave, fmt, _, pcm, channels, rate, _, _, bits, data, length = struct.unpack(
        "<4sI4s4sIHHIIHH4sI", header
    )
    assert (riff, wave, fmt, data) == (b"RIFF", b"WAVE", b"fmt ", b"data")
    assert (pcm, channels, rate, bits) == (1, 1, 24_000, 16)
    assert (size, length) == (44, 8)


def test_every_api_shape_the_catalog_accepts_has_a_client():
    """`synthesize` looks the client up by the catalog's shape; one without a client
    would be a KeyError mid-run rather than an entry dropped from the picker."""
    from app.services.text_to_speech.clients import CLIENTS
    from app.services.text_to_speech_models import SUPPORTED_APIS

    assert frozenset(CLIENTS) == SUPPORTED_APIS
