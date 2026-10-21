"""The `generate_speech` tool, and the text the model reads before calling it.

The clip is made by the provider the binding chose, through
:func:`app.services.text_to_speech.synthesize`, and kept where a generated image is
kept (:mod:`app.agents.capabilities._generated`) - so a person hears it where they
would have seen the picture, and a later step finds it under `output/`.

**The author bounds which voices the model may choose.** The usual voice, and
any others the binding lists, are offered as an `enum` in the tool's schema with
what each is for (:mod:`app.agents.capabilities._choices`); a binding with one
voice offers no choice at all.

**The budget is asked before the call, with the call's price.** Speech is sold per
character, so what a clip costs is known before it is made, and a run is refused
a clip that would carry it past a cap rather than only the call after the cap is
reached. What it cost is booked piece by piece as each one's audio arrives, so a
failure or a cancelled run partway through a long text still books the pieces
that came back: the provider billed them. Calls run one at a time, because the
check reserves nothing.

**Whose mistake decides the shape of a failure** (`_failures.py`). A text that is
empty, too long or refused by the provider is the model's to fix, so it is
steered. A provider that is down or rate limiting is transient, also steered. A
refused key, an unknown voice and a spent budget are nobody the model can fix -
they are the author's or the operator's - so they are returned as the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ValidationError
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._choices import Choice, schema_for
from app.agents.capabilities._failures import steer
from app.agents.capabilities._generated import store_generated
from app.agents.capabilities.budget import can_afford_ambient_call, record_ambient_cost
from app.agents.deps import AgentDeps
from app.services.text_to_speech import SpeechFailure, SpeechProviderError, synthesize
from app.services.text_to_speech_models import by_provider, price_per_character

MEDIA_TYPES = {"mp3": "audio/mpeg", "wav": "audio/wav"}

MAX_INSTRUCTIONS = 1000
"""The longest direction on how to speak. It goes to the provider with every piece
of a long text and is not priced, so it is kept to a direction rather than a text."""


@dataclass(frozen=True)
class OfferedVoice:
    """A voice the model may choose, and what it reads about it."""

    id: str
    note: str | None = None


class GeneratedSpeech(BaseModel):
    """What `generate_speech` returns - a reference to the clip, not the bytes.

    The interface plays the clip from `url`; the model is told to say what it
    recorded and leave this payload alone, as it does for a generated image.
    `filename` and `url` are absent only on a run with no organization to scope
    storage to (a preview, a test), where the clip was made but not kept.
    """

    kind: Literal["generated_speech"] = "generated_speech"
    filename: str | None = None
    url: str | None = None
    media_type: str
    voice: str
    characters: int
    workspace_path: str | None = None


def parse_generated_speech(result: str) -> GeneratedSpeech | None:
    """Parse a `generate_speech` result, or `None` for any other text."""
    try:
        payload = GeneratedSpeech.model_validate_json(result)
    except ValidationError:
        return None
    return payload if payload.kind == "generated_speech" else None


def _cost(price: Decimal | None, characters: int) -> Decimal | None:
    return None if price is None else price * characters


def build_speech_toolset(
    *,
    provider: str,
    model: str,
    voice: str,
    voices: tuple[OfferedVoice, ...],
    audio_format: str,
    max_characters: int,
    api_key: str | None,
) -> FunctionToolset[AgentDeps]:
    """A `generate_speech` tool bound to one provider, model and key.

    Everything the model must not choose is closed over. It chooses the words,
    one of the voices the author offered, and - where the model reads one - a
    direction on how to say them.
    """
    ledger_name = f"{provider}:{model}"
    usual_voice = voice
    voice_ids = tuple(offered.id for offered in voices)

    async def generate_speech(
        ctx: RunContext[AgentDeps],
        text: str,
        voice: str | None = None,
        instructions: str | None = None,
    ) -> str:
        """Speak a text aloud as an audio clip.

        Use this when the user asks to hear something - a voice-over, a narration,
        a spoken summary, a pronunciation. Put exactly the words to be spoken in
        `text`, written as they should sound: spell out numbers, dates and
        abbreviations that would be read wrongly, and add no stage directions. Say
        how it should sound in `instructions`. The interface stores the clip and
        plays it to the user, so say in one line what you recorded and leave the
        returned JSON alone.

        Args:
            text: The words to speak. A text over this agent's limit is refused
                with the limit stated; split it into several calls.
            voice: Who speaks - for a dialogue, a voice per speaker, one call each.
                Left out, the agent's usual voice.
            instructions: How to say it - tone, pace, emotion, accent, e.g.
                "warm and unhurried". Ignored by voices that take no direction.

        Returns:
            A JSON reference to the clip, already on its way to the user. Or, where
            nothing was spoken, a sentence saying why.
        """
        if api_key is None:
            # Unreachable once published - a missing required secret is refused at
            # publish and again at build. A retry rather than a crash for the
            # preview and test paths that build without a key.
            return steer(ctx, "Text to speech has no API key configured.")
        spoken = text.strip()
        if not spoken:
            return steer(ctx, "`text` is empty. Pass the words to speak.")
        if len(spoken) > max_characters:
            return steer(
                ctx,
                f"`text` is {len(spoken)} characters and this agent speaks at most "
                f"{max_characters} in one call. Split it into several calls.",
            )
        if instructions is not None and len(instructions) > MAX_INSTRUCTIONS:
            return steer(
                ctx,
                f"`instructions` is a direction on how to speak, at most {MAX_INSTRUCTIONS} "
                "characters. Shorten it.",
            )

        speaker = voice or usual_voice
        if speaker not in voice_ids:
            if len(voice_ids) == 1:
                return steer(ctx, f"This agent speaks only in {usual_voice}; leave `voice` out.")
            return steer(ctx, f"`voice` must be one of {', '.join(voice_ids)}.")

        entry = by_provider(provider)
        chosen = entry.model(model) if entry is not None else None
        if entry is None or chosen is None:
            # The binding was valid when it was published; the catalog has since
            # dropped the model. Only the author can choose another.
            return (
                "Not spoken: this agent's speech model is no longer offered. Its author "
                "needs to choose another in the agent's settings."
            )
        price = price_per_character(chosen, on=datetime.now(UTC).date())
        estimate = _cost(price, len(spoken))
        if not await can_afford_ambient_call(estimate or Decimal(0)):
            if estimate is None:
                return "Not spoken: this run has spent its budget."
            return (
                f"Not spoken: this clip would cost about ${estimate:.4f}, more than the "
                "budget this run has left."
            )

        try:
            speech = await synthesize(
                entry,
                model=model,
                voice=speaker,
                text=spoken,
                audio_format=audio_format,
                api_key=api_key,
                instructions=instructions,
                # Booked piece by piece, as each one's audio arrives, so a failure
                # or a cancelled run partway through a long text still books the
                # pieces that came back.
                on_spoken=lambda characters: record_ambient_cost(
                    ledger_name, _cost(price, characters)
                ),
            )
        except SpeechProviderError as exc:
            match exc.failure:
                case SpeechFailure.CREDENTIALS:
                    return (
                        "Not spoken: the speech provider refused this agent's API key. Its "
                        "author needs to replace the key in the vault."
                    )
                case SpeechFailure.NOT_FOUND:
                    return (
                        "Not spoken: the speech provider does not know this agent's voice "
                        "or model. Its author needs to choose another in the agent's settings."
                    )
                case SpeechFailure.REJECTED:
                    return steer(
                        ctx,
                        "The speech provider refused this request - the text, the voice or a "
                        "setting. Rephrase or shorten the text, or answer without audio.",
                    )
                case _:
                    return steer(ctx, f"{exc.message} Try once more, or answer without audio.")

        stored = await store_generated(ctx, speech.data, filename=f"speech.{speech.audio_format}")
        return GeneratedSpeech(
            filename=stored.filename,
            url=stored.url,
            media_type=MEDIA_TYPES[speech.audio_format],
            voice=speaker,
            characters=speech.characters,
            workspace_path=stored.workspace_path,
        ).model_dump_json()

    toolset: FunctionToolset[AgentDeps] = FunctionToolset()
    # One clip at a time: the budget is asked with a clip's price and reserves
    # nothing, so two clips priced at once could each fit and together pass a cap.
    toolset.add_function(
        generate_speech,
        takes_ctx=True,
        sequential=True,
        prepare=schema_for(
            {
                "voice": Choice(
                    voice_ids,
                    usual=usual_voice,
                    notes={offered.id: offered.note for offered in voices},
                )
            }
        ),
    )
    return toolset
