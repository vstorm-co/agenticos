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
binding's choice from a catalog, and the key is one vault secret whose purpose is
the chosen provider.

## Cost

Speech is sold per character, so a clip's price is known before it is made. The
tool asks the budget with that price (`can_afford_ambient_call(estimate)`) and
refuses a clip that would carry the run past a cap, rather than only refusing the
call after a cap is reached. What was spoken is then booked with
`record_ambient_cost`. A long text fails partway at most once per piece, and the
pieces spoken before it are booked too - the provider billed them even though the
half-clip is discarded. `max_characters` bounds what one call can cost at all.

Token-billed models (OpenAI's `gpt-4o-mini-tts`, Gemini) are priced in the
catalog per character of typical speech. That is an estimate of what the provider
will bill, and it is the number that can be known before the call.

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
| Provider rate limiting or unavailable | `steer` - transient, worth one more try |
| Key refused, voice or model unknown, model dropped from the catalog | Returned - only the author or the operator can fix it |
| Budget spent | Returned - a refusal, never a retry |

The provider's own error text is logged where it is received and never reaches
the model: it is not text this repository controls.
