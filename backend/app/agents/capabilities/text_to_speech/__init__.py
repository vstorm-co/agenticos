"""Text to speech capability - speak a text aloud as an audio clip."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.agents.capabilities._config_refusal import Refusal, refused_at
from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.text_to_speech._capability import TextToSpeech
from app.agents.capabilities.text_to_speech._toolset import OfferedVoice
from app.core.secret_kinds import ApiKeySecret, SecretCondition, SecretKind, SecretRequirement
from app.services.text_to_speech import ACCOUNT_VOICE_ID
from app.services.text_to_speech_models import (
    SpeechModel,
    TextToSpeechProvider,
    by_provider,
    default_choice,
    providers,
)

__all__ = ["TextToSpeech", "TextToSpeechConfig", "VoiceChoice"]

MAX_VOICES = 20
"""The most other voices one agent may be offered. Each is a line in the tool's
schema the model reads on every turn, so a library's worth is a cost, not a choice."""


class VoiceChoice(BaseModel):
    """One more voice the agent may speak in, and what it is for."""

    id: str = Field(
        title="Voice",
        min_length=1,
        description="A voice the model offers, or - for ElevenLabs - a voice id from your library.",
    )
    note: str | None = Field(
        title="What it is for",
        default=None,
        max_length=120,
        description=(
            "A few words the agent reads to tell this voice from the others, such as "
            "'Anna, the narrator'. Catalog voices are described already."
        ),
    )


class TextToSpeechConfig(BaseModel):
    """How this agent speaks.

    `provider` and `model` are the decision; the rest default to what the catalog
    lists first, so turning the capability on is enough to speak - except on a
    provider whose voices belong to the account, where only the author knows
    which of theirs to use.
    """

    provider: str = Field(
        title="Provider",
        default_factory=lambda: default_choice()[0],
        description=(
            "Whose voices speak. Offered: the providers in "
            "`app/core/catalog/text_to_speech_models.json` whose key the vault can hold."
        ),
    )
    model: str = Field(
        title="Speech model",
        default_factory=lambda: default_choice()[1],
        description=(
            "Which of that provider's speech models speaks. A model outside the catalog is "
            "refused here rather than mid-run."
        ),
    )
    voice: str | None = Field(
        title="Voice",
        default=None,
        description=(
            "The voice that speaks unless the agent chooses another; left empty, the model's "
            "first. ElevenLabs voices belong to your account, so for ElevenLabs paste the "
            "voice id from your voice library."
        ),
    )
    voices: list[VoiceChoice] = Field(
        title="Allowed voices",
        default_factory=list,
        max_length=MAX_VOICES,
        description=(
            "The only voices the agent may switch to instead of the one above, per clip - "
            "for a dialogue, or a narrator and a character. Left empty, it may choose any "
            "voice the model offers - for ElevenLabs, any voice id in your account."
        ),
    )
    output_format: Literal["mp3", "wav"] | None = Field(
        title="File format",
        default=None,
        description=(
            "mp3 is smaller, wav is uncompressed. Left empty, the provider's first format - "
            "Gemini returns wav only."
        ),
    )
    max_characters: int = Field(
        title="Longest text",
        default=5000,
        ge=1,
        # A clip is held whole before it is stored, and WAV runs about 48 kB a
        # second: ten thousand characters is some eleven minutes and 32 MB, where
        # a hundred thousand was half a gigabyte buffered several times over.
        le=10_000,
        description="The most text one call may speak, which caps what a single call can cost.",
    )

    @model_validator(mode="after")
    def _must_be_offered(self) -> TextToSpeechConfig:
        """Refuse a choice the provider would refuse on the first call.

        The pair, the voice, the other voices and the format are each checked
        against the catalog, because each fails differently mid-run: an unknown
        model is a bad request, a voice the model lacks is a not-found, and a format
        the provider does not return would be bytes stored under the wrong extension.
        Each is refused at its own field, so the Builder can mark the control it is
        about.
        """
        title = type(self).__name__
        entry = by_provider(self.provider)
        model = entry.model(self.model) if entry is not None else None
        if entry is None or model is None:
            offered = "; ".join(
                f"{candidate.provider}: {', '.join(item.id for item in candidate.models)}"
                for candidate in providers()
            )
            reason = f"{self.provider}/{self.model} cannot speak. Offered: {offered}."
            raise refused_at(title, [(("model",), reason, self.model)])
        if entry.account_voices and not (self.voice or "").strip():
            reason = f"{entry.name} voices belong to your account: name one by its voice id."
            raise refused_at(title, [(("voice",), reason, self.voice)])
        if self.voice is not None and (problem := _voice_problem(entry, model, self.voice)):
            raise refused_at(title, [(("voice",), problem, self.voice)])
        _refuse_listed_voices(entry, model, self.voices)
        if self.output_format is not None and self.output_format not in entry.formats:
            reason = f"{entry.name} returns {', '.join(entry.formats)}, not {self.output_format}."
            raise refused_at(title, [(("output_format",), reason, self.output_format)])
        return self

    def offering(self) -> TextToSpeechProvider:
        """The catalog entry this configuration was validated against."""
        entry = by_provider(self.provider)
        if entry is None:
            raise ValueError(f"{self.provider} is no longer offered for speech")
        return entry

    def chosen_model(self) -> SpeechModel:
        """The catalog's model this configuration was validated against."""
        model = self.offering().model(self.model)
        if model is None:
            raise ValueError(f"{self.model} is no longer offered for speech")
        return model

    def resolved_voice(self) -> str:
        """The voice to speak in: the one chosen, or the model's first."""
        if self.voice:
            return self.voice.strip()
        return self.offering().voices_for(self.chosen_model())[0].id

    def offered_voices(self) -> tuple[OfferedVoice, ...] | None:
        """Every voice the agent may speak in, the usual one first - or `None` for
        any voice id in the account.

        With no voices listed, a catalog provider offers every voice the model has,
        and an account provider any id in the account, which no catalog can list.
        A catalog voice is described by the catalog; an account voice only by the
        note its author wrote, since an id says nothing about who it sounds like.
        """
        entry = self.offering()
        catalog = {voice.id: voice for voice in entry.voices_for(self.chosen_model())}
        if not self.voices and entry.account_voices:
            return None
        notes = {choice.id.strip(): choice.note for choice in self.voices}
        others = list(notes) if self.voices else list(catalog)
        offered: list[OfferedVoice] = []
        for voice_id in dict.fromkeys([self.resolved_voice(), *others]):
            known = catalog.get(voice_id)
            if known is not None:
                note = f"{known.name}, {known.description}" if known.description else known.name
            else:
                note = notes.get(voice_id)
            offered.append(OfferedVoice(id=voice_id, note=note or None))
        return tuple(offered)

    def resolved_format(self) -> str:
        """The format to return: the one chosen, or the provider's first."""
        return self.output_format or self.offering().formats[0]


def _voice_problem(entry: TextToSpeechProvider, model: SpeechModel, voice: str) -> str | None:
    """Why the provider would refuse a voice - not an id, or not the model's - or None."""
    if entry.account_voices:
        if not ACCOUNT_VOICE_ID.fullmatch(voice.strip()):
            return f"{voice!r} is not a voice id: letters, digits, '-' and '_' only."
        return None
    offered = [voice.id for voice in entry.voices_for(model)]
    if voice not in offered:
        return f"{model.id} has no voice {voice!r}. Offered: {', '.join(offered)}."
    return None


def _refuse_listed_voices(
    entry: TextToSpeechProvider, model: SpeechModel, voices: list[VoiceChoice]
) -> None:
    """Refuse the allowed voices row by row, each at its own `voices.N.id`, so the
    Builder marks every bad row at once."""
    refusals: list[Refusal] = []
    seen: set[str] = set()
    for index, choice in enumerate(voices):
        voice = choice.id.strip()
        # Two notes for one voice would leave the agent reading only the last.
        problem = _voice_problem(entry, model, choice.id) or (
            "This voice is listed already." if voice in seen else None
        )
        seen.add(voice)
        if problem is not None:
            refusals.append((("voices", index, "id"), problem, choice.id))
    if refusals:
        raise refused_at("TextToSpeechConfig", refusals)


@register(
    id="text_to_speech",
    name="Text to speech",
    category="analysis",
    description="Speak a text aloud as an audio clip.",
    tools=(
        CapabilityToolInfo(
            id="generate_speech",
            description="Speak a text aloud as an audio clip.",
        ),
    ),
    config_schema=TextToSpeechConfig,
    # Speaking spends money on a provider key and produces a recording a person
    # may publish - in somebody's voice, where it is a cloned one - so every call
    # is a candidate for the approval gate, as an image is.
    side_effecting=True,
    secret=SecretRequirement(
        kind=SecretKind.API_KEY,
        description="The API key for the chosen speech provider",
        # Every provider needs a key, so this never makes one optional. It is
        # what tells the Builder the chosen provider *is* the key's purpose, so
        # the picker offers ElevenLabs keys for ElevenLabs rather than every
        # API key in the vault (#2258).
        required_when=SecretCondition(
            field="provider", equals=tuple(entry.provider for entry in providers())
        ),
    ),
)
def _build(ctx: CapabilityBuildContext) -> TextToSpeech:
    config = ctx.config if isinstance(ctx.config, TextToSpeechConfig) else TextToSpeechConfig()
    api_key = (
        ctx.secret.api_key.get_secret_value() if isinstance(ctx.secret, ApiKeySecret) else None
    )
    return TextToSpeech(
        provider=config.provider,
        model=config.model,
        voice=config.resolved_voice(),
        voices=config.offered_voices(),
        audio_format=config.resolved_format(),
        max_characters=config.max_characters,
        api_key=api_key,
    )
