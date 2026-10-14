# The ML services

Four services on this platform can be called on their own, without starting a
conversation and without running an agent: document analysis, OCR, speech to
text and personal data detection. They are the same implementations the agents
use, reached directly — one set of parsers, one set of detectors, one
transcription client.

They exist because another component may need them. A queue that has to read a
scanned application form, a batch job redacting an export, a service that wants
a transcript — none of those want a chat window, and none of them should have to
pretend to be one.

## What is delivered, and what is not

Every service family is a row here. **served** means an endpoint on this
deployment answers it with the engine named beside it. **dependency** means the
family is required and something is missing, and the note says what.
**prepared** is architecture preparation: no engine ships, and the seam it would
arrive through is named.

`GET /api/v1/ml/services` answers with this same table, so an integration can
read it rather than trusting a page.

| Service | Requirements | Endpoint | State | Engine |
|---|---|---|---|---|
| `document_analysis` | FA-069, FA-070 | `POST /api/v1/ml/documents/analyze` | served | LiteParse or PyMuPDF, locally |
| `ocr` | FA-069, FA-071 | `POST /api/v1/ml/documents/ocr` | served | LiteParse OCR: bundled Tesseract, or a registered OCR server |
| `speech_to_text` | FA-069, FA-072 | `POST /api/v1/ml/audio/transcriptions` | served | The organization's own transcription endpoint |
| `pii_detection` | FA-069, FA-073 | `POST /api/v1/ml/privacy/pii` | served | The pattern detectors the guardrails use |
| `pii_named_entities` | FA-073, DA-007 | — | dependency | None on this deployment |
| `image_analysis` | FA-074 | — | prepared | None on this deployment |

Two rows say no, and both say why. **Named entities** — a person's name, a
postal address — are not pattern-shaped, so no regular expression finds them:
that needs a named-entity model per language in scope.
The detection endpoint carries the extra categories the day one is provided, and
until then it does not claim them. **Image analysis** is marked as future scope
in the requirements themselves.

## Calling one

Authentication, the organization header and the error envelope are the
[HTTP API](api.md)'s own. There is no separate key, no separate host and no
second way in, which is deliberate: a surface with its own front door is a
surface with its own mistakes.

One permission gates all four: **`ml:invoke`**. It is deliberately not
`agents:run` — an integration that parses documents should not thereby be able
to spend the organization's model budget. Every role but Viewer holds it.

```bash
curl -X POST "$BASE/api/v1/ml/documents/ocr" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -F "file=@scan.pdf" \
  -F "language=deu"
```

The answer carries the pages in order, the prepared chunks, and the file's size
and hash:

```json
{
  "filename": "scan.pdf",
  "filetype": "pdf",
  "byte_size": 184320,
  "content_hash": "9f2c…",
  "pages": [{"page_num": 1, "content": "Antrag auf …"}],
  "chunks": ["Antrag auf …"]
}
```

### Document analysis

`POST /api/v1/ml/documents/analyze` reads what a document already carries. The
`parser` field chooses between `liteparse`, which preserves the layout and reads
office formats where LibreOffice is installed, and `pymupdf`, which reads PDFs
and is faster. `chunk_size`, `chunk_overlap` and `chunking_strategy` shape the
prepared chunks; the strategies are `recursive`, `fixed` and `markdown`, and a
fourth spelling is refused rather than quietly treated as `recursive`.

`chunk_overlap` has to be **smaller** than `chunk_size`. Equal is refused, and
not for tidiness: the splitter accepts it and then advances by about one
separator per chunk while keeping an almost complete copy of the last one, so a
legal upload answers with a document multiplied many times over.

A document with nothing readable in it is refused rather than answered with an
empty page list, and the refusal says to call OCR instead — which is what a scan
parsed for its text layer always needs.

### OCR

`POST /api/v1/ml/documents/ocr` recognises the text on every page, whether or
not the page carries a text layer. That is the difference from ingestion, which
auto-detects and skips recognition where the text is already there: a caller who
asked for OCR asked for the pages to be read as images.

`language` is a Tesseract code, which is three letters — `pol`, not `pl`. The
shipped image installs **`eng` and `pol`**, and those are the two the endpoint
accepts: a code with no language pack behind it fails inside the parse, so it is
refused at the boundary instead. A deployment that installs more packs widens the
list in the same change.

`ocr_service_id` names an OCR server registered under
[local services](configuration.md), so a deployment running its own recognition
sidecar sends the pages there; omit it and the engine bundled with the parser
reads them. Either way the pages stay on the deployment's own network.

**A `.docx` is refused here**, although the parser reads one. Ingestion routes
office documents to the native reader before it consults the OCR parser, so
accepting one would extract its existing paragraphs, skip its scanned pages and
say nothing about the difference. Convert it to PDF.

One call recognises at most **200 pages** and has **120 seconds**, both narrower
than ingestion's, because a caller is waiting on this and nobody waits on an
ingestion.

### Speech to text

`POST /api/v1/ml/audio/transcriptions` transcribes a recording on the
organization's own credential. `provider` and `model` name what to use; omitting
**both** takes the deployment's first offered pair, and naming a provider without
a model takes that provider's first model. What it never does is fall back to the
default provider when a provider was named — that is how a recording meant for a
self-hosted engine ends up at a vendor.

A recording is also held to the transcription client's own 25 MB ceiling even
where `ML_MAX_UPLOAD_SIZE_MB` is higher, so an over-large recording is refused as
being over-large rather than reaching the engine and coming back as a 503 about a
credential.

The engine is whichever endpoint the organization's model profile for that
provider names. That is the answer to a deployment that may send no audio to a
vendor: point the profile at a self-hosted server speaking the same API and the
endpoint here is unchanged. An organization with no usable credential is
refused, saying so — nothing is assumed to exist that an operator has not
configured.

Which credential, when the organization has several for one provider: **a
keyed profile first**, the first in label order; then a keyless one, only if it
names an endpoint of its own; and, failing both, **an API key stored in the
vault** with that provider as its purpose, the first by name, sent to the
catalog's address. A keyless request carries no `Authorization` header, and
never the deployment's `OPENAI_API_KEY`. Keyed first is what keeps a channel bot
transcribing on OpenAI after somebody adds a keyless `openai` profile for a chat
proxy that serves no `/audio/transcriptions`.

The vault fallback reads only keys **visible to the whole organization**: a
member's private key in the vault is not picked up for a recording, because
what it would pay for is everybody's - a voice note in a channel, a dictation
in somebody else's chat. So an organization that keeps an OpenAI key in the
vault and runs no OpenAI chat model transcribes on it without a model profile
it does not need.

A model profile is used as configured, so a profile that points at a private
key transcribes on it, as a chat run on that profile spends it. The same order serves this endpoint, dictation and channel voice notes. The
vault's list of the agents using a key does not include this use, because no
agent binds the key.

A refusal says why in `details.reason`, here and on
[dictation](#dictation-in-chat) alike. The provider's own error text is logged
and never returned, because a provider client puts the request URL, key and
all, in its message.

| `reason` | Status | What happened |
|---|---|---|
| `not_configured` | 503 | No usable credential for the provider; for dictation, also server dictation not set up |
| `empty` | 400 | The engine heard no speech, or the recording has no bytes |
| `unsupported_type` | 400 | Dictation only: the recording is not WebM, Ogg, MP4 or WAV audio, or - on a hosted page or a widget - its length cannot be read |
| `too_large` | 400 | Over 25 MB, or over the organization's dictation cap in bytes or in measured length; `details.limit_seconds` names the limit |
| `provider_error` | 503 | The provider refused or failed the request |
| `timeout` | 503 | The provider did not answer within 60 seconds |

#### Dictation in chat

`POST /api/v1/agents/{agent_id}/dictation` is the microphone in the
[`/chat` composer](console.md#dictation), when the organization transcribes on
the server. It takes one recording as `file` and answers `{"text": "..."}`,
which the composer puts into the box for the person to edit; nothing is sent
until they press Send. The caller names no provider, model or language — those
[resolve](#which-engine-a-recording-reaches) from the agent and the
organization — and the person may dictate to any agent they may run, a Viewer
with a `use` grant on it included. An agent they may not run answers 404, as
everywhere else.

What it reads from the organization, set on the
[Voice card](console.md#the-voice-card) by somebody holding `org:settings`:
`chat_dictation` (`off`, `browser` or `server`; anything but `server` is refused
as `not_configured`), `speech_to_text_provider` and `speech_to_text_model` (a
pair from the speech-to-text catalog), `speech_to_text_language` (an ISO-639-1
code, or null to let the engine detect it) and `dictation_max_seconds` (10 to
600, 300 by default). The engine and the longest dictation are always the
organization's; the agent can only change which provider, model and language.

`GET /api/v1/agents/{agent_id}/dictation`, with the same access, says whether
the microphone will work before anybody records: `engine`, `max_seconds`,
`provider`, `format`, `ready` and `server_available`. `server_available` needs a
pair that resolves for this agent, the catalog still offering it, and a
credential for its provider in the organization - checked for existence, never
opened; `ready` is that, the `server` engine and the agent not being archived. The embed form reads
`server_available`, because a [hosted page or a widget](channels.md#dictation-on-a-widget-or-a-hosted-page)
is not gated by the `/chat` engine.

`provider` is the one a recording would reach, and `format` what to record in
for it - `webm` or `wav`, from the speech-to-text catalog, so no client keeps a
list of its own. An agent with nothing published answers from the
organization's settings.

The recording has to be `audio/webm`, `audio/ogg`, `audio/mp4` or `audio/wav`,
a codec suffix allowed, with `audio/x-wav` and `audio/wave` read as `audio/wav`,
`audio/x-m4a` and `audio/m4a` as `audio/mp4`, and `audio/opus` and `audio/x-ogg`
as `audio/ogg`.
The first three are what browsers' `MediaRecorder` produces; the composer
records WAV itself when `format` says `wav`, which the catalog says for Mistral
(see the note below). The
provider receives the recording as `recording.webm`, `recording.ogg`,
`recording.m4a` or `recording.wav`, from the same table that names a channel
voice note `voice.<ext>`.

The route reads at most 25 MB of the body; the organization's byte cap,
`dictation_max_seconds × 32 KB`, is applied to what was read. A body the
deployment's request limit refuses before the route runs answers 413 without a
`reason`, which the composer reads as `too_large`.

Then the recording's **length is read from its container** - the WAV header, the last
Ogg page, the WebM block timestamps, the MP4 movie or fragment headers - and a
recording longer than `dictation_max_seconds` is refused as `too_large` before
the provider is called, with three seconds' grace because the composer stops on
a once-a-second tick. A recording whose length cannot be read is accepted here,
under the byte cap; a [hosted page or a widget](channels.md#what-it-costs-and-what-bounds-it)
refuses one.

Each person may dictate `RATE_LIMIT_DICTATION_PER_MINUTE` times a minute, 10 by
default, on a counter of its own, so dictating does not spend an integration's
ML quota. Every dictation leaves one [call record](#what-is-recorded), under
`speech_to_text` and counted in seconds of audio. The composer sends the length
it recorded as a `duration` form field beside `file`. **The audio is never stored**: it is
discarded when the call returns, and the text exists only in the response.
Cancelling in the browser does not cancel a recording already sent — the
provider still transcribes it, bills the organization's account for it, and the
call is recorded.

!!! note "On Mistral the browser records WAV, and fewer languages are transcribed"

    Mistral documents WAV and MP3 input for Voxtral, not WebM or Opus, which is
    what Chrome and Firefox record. So when the provider a recording resolves to
    is Mistral, the composer records 16 kHz mono 16-bit WAV in every browser
    instead. The upload is about twice as large — 32,000 bytes a
    second — but the length limit is the same, because a WAV recording of
    `dictation_max_seconds` fits under the cap.

    The language list is Whisper's, which OpenAI and Groq accept. Mistral states
    13 languages for Voxtral, so a pinned language it does not take comes back
    as `provider_error`. On Mistral, leave the language on auto-detect and try a
    recording before relying on it.

#### Which engine a recording reaches

Three places can name a speech-to-text engine: the organization's
[Voice card](console.md#the-voice-card), an agent's
[`speech_to_text`](reference/spec.md#speech-to-text) override, set on its own
[Voice card](console.md#an-agents-own-engine) and live once published, and a
[channel bot](channels.md#what-every-channel-shares). They resolve in two halves:

| What | Comes from the first that sets it |
|---|---|
| Provider and model, as a pair | The bot, then the agent, then the organization |
| Language | The agent, then the organization, then the engine detects it |

So a Polish agent in an organization set up for English pins `language: pl` and
keeps the organization's provider. A bot has no language of its own; the
agent's or the organization's applies to its own pair too. Nothing resolving
means nothing is transcribed: dictation answers `not_configured`, and a bot says
it cannot listen.

Dictation reads the agent's published default version, the one `/chat` runs. A
bot reads the agent its binding serves - never an agent somebody mentions with
`@slug`, because a recording is transcribed before mentions are routed - at the
version that binding's
environment pins, the one the run will use. A draft or archived agent has no
version anybody runs, and the organization answers alone.

### Personal data detection

`POST /api/v1/ml/privacy/pii` takes JSON rather than a file:

```bash
curl -X POST "$BASE/api/v1/ml/privacy/pii" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"text": "write to ada@example.com", "categories": ["email"]}'
```

```json
{
  "counts": [{"category": "email", "count": 1}],
  "total": 1,
  "redacted_text": "write to [redacted:email]"
}
```

Every category asked for is reported, including the ones that matched nothing —
"looked for and absent" and "not looked for" are different answers. The
categories are `email`, `iban`, `credit_card`, `us_ssn` and `phone`, and each
is shape-matched and then checked: Luhn for a card, ISO 7064 for an IBAN, the
country's numbering plan and digit grouping for a phone number, so a run of
digits is not reported as an account or a number.

A phone number written with `+` is found whatever its country; a national one,
such as `415-555-0132`, is read against the guardrails' default countries, `US,
GB, DE, PL`. The `phone_regions` field that changes that list belongs to an
agent's guardrails, not to this endpoint.

What comes back is counts and the redacted text, not the offsets of each match.
The detectors answer with rewritten text, and recovering positions would mean
copying their pattern table and their checksums — a copy that silently stops
agreeing with the original is worse than a narrower contract.

## What is recorded

Every call leaves a row: which service, which organization, who asked, how many
bytes went in, how much came out, how long it took and how it ended.
`GET /api/v1/ml/calls` reads them back, newest first, and
`GET /api/v1/ml/calls/{id}` reads one.

A refused call is recorded too, and its record is committed before the refusal
unwinds the request — a row merely added to that transaction would be rolled back
by the very refusal it describes, and an operator asking why an integration is
failing would be told the tenant made no calls at all.

**No content is kept.** The result goes back in the response and is not stored,
so a document parsed here does not become a document this deployment holds, and
text sent to be scanned for personal data is not retained in a table nobody
thought of as a document store. A call record another organization made is not
found, the same way every other row on this API is scoped.

Usage is counted in the unit the service works in — pages for a parse,
characters for a scan, seconds of audio for a transcription — and not in money.
The delivered services either run on the operator's own machines, where there is
no vendor price, or on the organization's own provider account, which bills it
directly. A figure nobody can reconcile against an invoice is worse than an
honest unit count. Transcription is not counted against an agent's
[budget](governance.md#budgets) either.

### Transcriptions

Speech to text is reached three ways, and each leaves the same row: the API
(`surface: api`), [dictation](#dictation-in-chat) (`chat`) and a
[channel bot's voice messages](channels.md#what-every-channel-shares)
(`channel`). The row adds the `provider` and `model`, the `agent_id` it was for -
the dictated-to agent, or the agent the bot serves - the `channel_bot_id`, and
`audio_ms`, the recording's length. A voice message's `requested_by` is the
person the sender is linked to while that person is still a member of the
organization, or nobody. Only a recording handed to the
provider is recorded; a bot switched off, or one with no engine to inherit,
asked nobody.

The length is the first of these that is known:

| Source | Who gives it |
|---|---|
| The recording itself | Dictation only: the length read from its container, as above |
| The provider's answer | OpenAI `whisper-1` (`usage.seconds`), Groq (`duration`, asked for with `response_format=verbose_json`), Mistral (`usage.prompt_audio_seconds`) |
| The platform's metadata | A Telegram voice note or audio file, a Slack clip |
| The browser | Dictation only: the `duration` the composer sends, clamped to the organization's longest dictation, because it is the client's word |

OpenAI's `gpt-4o-transcribe` and `gpt-4o-mini-transcribe` report tokens, not
seconds, and Mattermost states no length, so a voice message there on those
models has none. A successful row then counts `0` seconds with a null
`audio_ms` - unmeasured, not silent.

`GET /api/v1/ml/calls` narrows by `agent_id`, `channel_bot_id`, `surface`,
`since` and `until` as well as `ml_service`, always inside the caller's
organization: another tenant's agent id matches nothing. The agent, the bot and
the surface - as filters and as columns - need `runs:view`, like the summary
below. With `ml:invoke` alone a filter on them is refused with 403, and the
three come back null on every row.

`GET /api/v1/ml/calls/summary?days=30` adds up the successful transcriptions
over a window: `seconds` - each row's own `units`, the recording rounded up to
the second, added up, so the summary agrees with the listing - and `count`,
`count_unknown_length` for the recordings the seconds leave out, and the same by agent, by channel bot and by surface. It
needs `runs:view`, as [`GET /spend`](governance.md#what-the-cost-screen-shows) does, rather than
`ml:invoke`: the breakdown names agents and bots a Member may not see. The
organization's [Voice card](console.md#the-voice-card) shows it in one line.

## Limits

A single call accepts up to `ML_MAX_UPLOAD_SIZE_MB` megabytes, 25 by default,
and only that many bytes are read out of the body — an over-large submission is
refused without having been copied into memory first. One scan reads at most
200000 characters, and a scan that includes `phone` at most 10,000 digits: the
phone matcher costs tens of microseconds a digit, so a longer text is refused
rather than read. A caller may make `RATE_LIMIT_ML_PER_MINUTE` calls a minute,
30 by default, counted per caller rather than per address.

A rate limit counts **starts** and cannot see what is still running, which is the
wrong shape for work measured in minutes. So a worker also parses at most
`ML_MAX_CONCURRENT_PARSES` documents at once, 4 by default, and a call arriving
with every slot busy is refused with a `Retry-After` rather than queued: a caller
told to come back in a moment can, and one parked behind four scans has already
given up somewhere nobody here can see.

Execution is synchronous: the answer is the result, and there is no queue to
poll. That is honest about what is here rather than aspirational — a queued mode
would add its own states to the call record, which is the shape it would arrive
in.

## Deploying them separately

The services scale differently from the console. An OCR pass is CPU-bound
seconds on a thread; serving a dashboard is neither. So
`deploy/profiles/ml-services/` runs the API image a second time as a replica
that answers only these paths, with its own resources and its own scaling, and
the ingress in front routes `/api/v1/ml/` to it.

It is the same image and the same database, which is what keeps one
implementation serving both the agents and the direct callers. What is separate
is the process, the limits and the restart — which is what "deployed, updated
and scaled independently" asks for.

See `deploy/profiles/ml-services/README.md` for the overlay and what it expects.
