# Text to speech

Exposes one tool, `generate_speech`, which speaks a text aloud and returns a
reference to the clip. The audio is made by the provider the binding chose -
OpenAI, ElevenLabs or Gemini today - stored organization-scoped, and played to
the user by the interface, exactly where a generated image would be shown
(#2259).

## Layout

| File | Holds |
|---|---|
| `_toolset.py` | `build_speech_toolset`: the tool, its prompt, the budget check, the metering and the storage; plus `GeneratedSpeech`/`parse_generated_speech`, the wire format |
| `_capability.py` | The `TextToSpeech` dataclass and `get_toolset()` |
| `__init__.py` | `TextToSpeechConfig`, the registry entry, the secret and exports |

What is *offered* - providers, models, voices, formats, prices - is the catalog,
`app/core/catalog/text_to_speech_models.json` read by
`app/services/text_to_speech_models.py`. How each provider is *called* is
`app/services/text_to_speech/`. This package only decides what one tool call does.

## Why the same shape as image generation

A person asking for a voice-over and a person asking for a picture expect the
same thing: a file in the conversation they can play or open, saved where the
agent can build with it next. So the clip goes through
`app/agents/capabilities/_generated.py`, the same helper `generate_image` uses -
stored per organization and served from `GET /api/v1/generated/{filename}`, and
written under `output/` when a workspace is open. The provider and model are a
binding's choice from a catalog, and the key is one vault secret; the Builder
offers the keys whose purpose is the chosen provider. Publish does not yet refuse a
key stored for another provider - that is #2258, for every media capability.

## The voices the agent may choose

`voice` is a default: the one the agent speaks in unless it asks for another.
`voices` is the limit - the only others it may switch to, for a dialogue or a
narrator and a character. Left empty, every voice the model has is allowed, and
on ElevenLabs any voice id in the account, cloned voices included; the Builder
says so as a warning rather than leaving it to a field description, since an
agent picking a cloned voice nobody chose is the risk the list exists to bound.

The voices reach the model as an `enum` on the tool's `voice` parameter
(`_choices.py`), with the usual one as the default and what each is for: the
catalog's description, or for an account voice the author's `note`, since an id
says nothing about who it sounds like. An open account voice cannot be listed, so
the parameter stays a free string and the tool checks its shape. Capped at 20:
every entry is a line the model reads on every turn.

## Cost

Speech is sold per character, so a clip's price is known before it is made. The
tool asks the budget with that price (`can_afford_ambient_call(estimate)`) and
refuses a clip that would carry the run past a cap, rather than only refusing the
call after a cap is reached. What was spoken is booked with `record_ambient_cost`
piece by piece, as `synthesize` reports each one spoken: a long text that fails, or
a run cancelled partway through it, leaves nothing the provider billed unbooked,
even though the half-clip is discarded. `max_characters` bounds what one call can
cost at all. The check reserves nothing, so the tool runs one call at a time
(`sequential`): two clips priced together could each fit and together pass a cap.

`instructions` - a direction on how to speak - is capped at 1,000 characters and is
not priced. It goes to the provider with every piece of a long text.

Token-billed models (OpenAI's `gpt-4o-mini-tts`, Gemini) are checked at a price
per character of typical speech, the number that can be known before the call.
Gemini's catalog entry also lists its token rates, and since its audio comes back
as raw PCM, each piece is then booked from the audio's length - text tokens in,
25 audio tokens a second out - rather than its characters: a direction to speak
slowly makes the same text cost more (#2351). OpenAI's MP3 carries no length this
reads, so it stays booked by its characters.

## What it deliberately does not do

- **Voices from the account's library are not listed.** ElevenLabs' voices belong
  to the account and its shared defaults expire on 2026-12-31, so a binding names
  one by id. Listing them needs the binding's key, which a catalog route does not
  read.
- **No streaming.** The clip is returned whole, as an image is; a player in the
  chat is the delivery, not a live voice.
- **No spoken replies on channels.** A voice note in Telegram or Slack is a
  separate decision about channels, not this tool.
- **No Ogg Opus.** Pieces of a long text are joined, and Ogg pieces cannot be.

## Failures

Whose mistake decides the shape (`capabilities/_failures.py`):

| Failure | Answer |
|---|---|
| Empty text, text over `max_characters`, text the provider refuses | `steer` - the model can fix its call |
| A voice the model chose that the provider does not know | `steer` - the model picked it, so the model can pick another |
| Provider rate limiting or unavailable | `steer` - transient, worth one more try |
| Key refused, the usual voice or the model unknown | Returned - only the author or the operator can fix it |
| Budget spent | Returned - a refusal, never a retry |

Only the provider's error code is logged (`provider_error_code.py`); its error
text is neither logged nor passed to the model: it is not text this repository
controls, and it may echo the key or the words sent.
