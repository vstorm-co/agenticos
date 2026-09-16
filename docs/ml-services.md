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
postal address, a telephone number — are not pattern-shaped, so no regular
expression finds them: that needs a named-entity model per language in scope.
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
prepared chunks; the strategies are `recursive`, `fixed` and `markdown`.

A document with nothing readable in it is refused rather than answered with an
empty page list, and the refusal says to call OCR instead — which is what a scan
parsed for its text layer always needs.

### OCR

`POST /api/v1/ml/documents/ocr` recognises the text on every page, whether or
not the page carries a text layer. That is the difference from ingestion, which
auto-detects and skips recognition where the text is already there: a caller who
asked for OCR asked for the pages to be read as images.

`language` is a Tesseract code, which is three letters — `deu`, not `de`.
`ocr_service_id` names an OCR server registered under
[local services](configuration.md), so a deployment running its own recognition
sidecar sends the pages there; omit it and the engine bundled with the parser
reads them. Either way the pages stay on the deployment's own network.

### Speech to text

`POST /api/v1/ml/audio/transcriptions` transcribes a recording on the
organization's own credential. `provider` and `model` name what to use, and
omitting them takes the deployment's first offered pair.

The engine is whichever endpoint the organization's model profile for that
provider names. That is the answer to a deployment that may send no audio to a
vendor: point the profile at a self-hosted server speaking the same API and the
endpoint here is unchanged. An organization with no usable credential is
refused, saying so — nothing is assumed to exist that an operator has not
configured.

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
categories are `email`, `iban`, `credit_card` and `us_ssn`, and each is
shape-matched and then checked: Luhn for a card, ISO 7064 for an IBAN, so a run
of digits is not reported as an account.

What comes back is counts and the redacted text, not the offsets of each match.
The detectors answer with rewritten text, and recovering positions would mean
copying their pattern table and their checksums — a copy that silently stops
agreeing with the original is worse than a narrower contract.

## What is recorded

Every call leaves a row: which service, which organization, who asked, how many
bytes went in, how much came out, how long it took and how it ended.
`GET /api/v1/ml/calls` reads them back, newest first, and
`GET /api/v1/ml/calls/{id}` reads one.

**No content is kept.** The result goes back in the response and is not stored,
so a document parsed here does not become a document this deployment holds, and
text sent to be scanned for personal data is not retained in a table nobody
thought of as a document store. A call record another organization made is not
found, the same way every other row on this API is scoped.

Usage is counted in the unit the service works in — pages for a parse,
characters for a scan — and not in money. The delivered services either run on
the operator's own machines, where there is no vendor price, or on the
organization's own provider account, which bills it directly. A figure nobody
can reconcile against an invoice is worse than an honest unit count.

## Limits

A single call accepts up to `ML_MAX_UPLOAD_SIZE_MB` megabytes, 25 by default,
and one scan reads at most 200000 characters. A caller may make
`RATE_LIMIT_ML_PER_MINUTE` calls a minute, 30 by default, counted per caller
rather than per address.

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
