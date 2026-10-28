# Models and providers

!!! tip "Deciding rather than configuring?"

    This page is the machinery. [Choosing a model](choosing-models.md) answers
    *which* model an agent should use — open weights or closed, what actually
    drives the bill, and why the choice is reversible.

The template this platform grew from built one model from environment variables.

That stops working the moment several organizations share a deployment: each needs
its own key, its own default, and the ability to rotate either without a redeploy.

So a model is constructed **per run**, out of the database:

```
model profile → credential → unsealed secret → provider client → Model
```

Nothing about which model an agent uses lives in `.env`.

## A model profile

A row in an organization: a label, a provider, a model id, default settings, and
which [vault secret](secrets.md) to authenticate with.

An agent's spec names one by `model_profile_id`, and the run resolves it.

!!! tip "The model id is free text on purpose"

    There is a picker to help, but the field accepts anything you type.

    A provider ships something the morning after any list here was warmed, and a
    field that cannot express "that one" is a field people work around by editing
    the spec by hand.

### A profile an agent cannot run on

A profile can name a model that cannot hold a conversation: a text-to-speech model
such as `gpt-4o-mini-tts`, a realtime voice model, a transcription model, an image
model, a video model or an embedding model. An agent on one fails on its first turn. Text to speech, image
generation and transcription do not use profiles: each feature names its own
provider and model.

The platform knows these models from its own catalogs (the realtime voice, text-to-speech,
transcription, image, video and embedding lists). `GET /providers/model-profiles`
marks each profile with `chat_capable` and `output_modalities`, and
`GET /providers/{provider}/models` marks each suggestion with `chat_capable`.
Those two fields also read a provider listing that states what each model emits
(OpenRouter and the Hugging Face router do), when the API process has already
fetched it. That listing only changes what a picker offers. It never refuses a
publish, because another API process may not have fetched it. The console also
updates saved profiles when a listing arrives later. Provider aliases such as
`openai_codex` and `google_cloud` use the corresponding vendor catalogs. Then:

- The Builder's model panel, the reviewer and specialist pickers, the follow-ups
  and browser step model fields and the knowledge-base image-description picker do
  not offer such a model. If an agent already names one, the Builder still shows
  it, marked as not a chat model. For a member who can manage connections, the
  Builder also lists the others, marked and not selectable, so they can be
  removed.
- The chat's model picker and the Builder's form for adding a model do not
  suggest such a model, and refuse one that is typed in.
- Publish refuses such a model as the agent's model, a reviewer's, a specialist's,
  the browser step model or the follow-ups model, and names it. It also refuses a
  profile whose fallbacks include such a model. The same check runs on rollback,
  on the draft check, on the Builder's test run and when a capability is enabled
  from chat. A stored version on such a model still loads, but it cannot be
  restored while its profile names a non-chat model or lists one as a fallback.
  Point that profile at a chat model, or publish a new version.
- A run leaves such a fallback out of its chain, the same as a deleted one, when
  it was added to the profile after publish.
- A conversation that names such a model in place of the agent's own, from the
  chat or through the API, is refused before the run starts.
- A model that the catalogs do not classify, such as an Ollama model or a model
  released this morning, is allowed. An unknown model is not a refusal. A profile
  with its own endpoint (`base_url`) is never classified, whatever its model id:
  the catalogs describe the provider's own API, and an OpenAI-compatible server
  can serve a chat model under any name.

The proactivity model picker follows the same rule. The stable catalog check also
runs when proactivity is configured and whenever a profile is resolved for an
ordinary text request, including image description at configuration and worker
time. Old configurations still load; replace an incompatible model before using
them. Switching off remains possible. Azure deployment names are not classified
from the catalog's base-model IDs.

### Changing a profile's key or endpoint

Agents name a profile by its id. To move a model to another key, another
endpoint or the other OpenAI API, edit the profile in place:
`PATCH /providers/model-profiles/{id}` changes `secret_id`, `base_url`, `api`,
`params` or `label` and keeps the id. Every agent on the profile uses the change
from its next run. Nobody has to republish anything.

In the Builder's model panel, change the key, the endpoint or the API of the model
in use. The button then reads **Update model**, and the panel says that every
agent on this model switches with it. **Add model** is still the button for
another provider or model, and for a model you give a name of its own. Use
**Name it something else** to give only this agent a separate model.

An edit has the same rules as creation and needs the same `connections:manage`
permission. A new key must be in this organization's vault, be visible to you,
and be stored for the profile's provider. A new endpoint checks the stored key in
the same way, because the endpoint is where the key is sent. A provider that needs
a key cannot lose it. A keyless provider with no key keeps an endpoint. A label
must stay unique.

If you change the endpoint and send no `api`, an API that was
only the old endpoint's default moves to the new endpoint's default, and an API
somebody chose stays. The audit log records `model_profile.updated` with the
names of the changed fields, not their values. You cannot change the provider or
the model id. Another model is another profile.

`connections:manage` is therefore the authority to move every agent on a model,
including agents you cannot edit: a new endpoint receives their requests from
the next run. Grant it to the people who manage the organization's models.

### A profile without a key

If you delete a key from the vault, its profiles stay with `secret_id` set to
null, and `GET /providers/model-profiles` marks them `missing_key: true`. A
profile saved with no key on purpose is different: a self-hosted model or a
gateway that authenticates nothing, on a keyless provider with an endpoint, such
as an Ollama on your network or an OpenAI-compatible server. It records that as
`runs_without_key` and keeps running. A gateway profile that had a key and lost
it is marked `missing_key` like any other. Then:

- Agent and chat model pickers do not offer it. If an agent already names it, the
  Builder shows it with a **no key** badge and tells you to give it a key.
- Publish refuses it and names the model. It also refuses a profile whose first
  three fallbacks include one with no key, because a run would skip it. A run on
  it fails with "no key configured".
- To repair it, open an agent on that model and choose a key under **Model**, then
  press **Update model**. Every agent on the model works again.

### Deleting a profile

`DELETE /providers/model-profiles/{id}` refuses a profile that agents use. The
answer is `409 IN_USE`, and `details.agents` lists each agent you can see, by id
and name. `details.hidden_agents` counts the agents you cannot see. A profile is
in use when an agent's draft, its served version or a version that an environment
pins names the profile anywhere: as the agent's model, a reviewer's or a
specialist's, or in a capability, such as the follow-ups model or the browser step
model.

Archived agents count, because unarchiving restores the version they
served. The refusal marks them `archived`: an archived agent cannot publish, so
delete it, or restore it and move it. Old versions that nothing serves do not
count. Move the other agents to another model first. To change only the key, edit the profile
instead.

### Fallbacks

A profile may list fallback profiles, tried in order. Only the first three are
used by the runner and checked at publish. One provider's outage should
not take an organization's agents down when it has a second key or a second
provider configured.

!!! warning "A fallback is invisible in the run record"

    The run row is written before the first request, carrying the **primary**
    profile's label, provider and secret id. If a fallback served the turn, the run
    still names the primary.

    So "what did we spend at OpenAI" and "which key is costing the most" answer
    with the profile that was *asked* first, not the one that answered. Worth
    knowing before you rely on those numbers during an outage.

### Model settings

Per profile, and overridable per agent through the spec's `model_settings`:
`temperature`, `top_p`, `max_tokens`, `parallel_tool_calls`, `timeout`. See
[the spec reference](reference/spec.md#model-settings).

**Prompt caching is on by default**, through Pydantic AI's provider-neutral
`cache` setting. Every request of a run re-sends the instructions, the tool
schemas and the whole history, so the stable prefix and the conversation are
marked as cache breakpoints and each request reads the one before it from cache.
It applies wherever a provider takes explicit caching - Anthropic, Bedrock's
Anthropic and Nova models, OpenRouter's Anthropic and Gemini models, OpenAI from
GPT-5.6 - and changes nothing on one that caches by itself, such as Google. A
profile turns it off with `cache: false`, or caches only the instructions and
tools with `cache: {"messages": false}`. A provider-specific flag a profile
already sets, such as `anthropic_cache_messages`, still wins for that profile.

Reasoning effort is **not** here. It is the
[`thinking` capability](reference/capabilities.md#thinking), because "reason
harder" is a decision about what the agent is *for* rather than a knob on a
connection — and because a spec that sets it as a model setting stops being
portable across a model swap.

### Responses or Chat Completions

OpenAI publishes two APIs for the same models, and a profile on `openai` or
`azure` stores which one its requests go to: `responses` or `chat`. Every other
provider serves one API and stores nothing here.

Neither is right everywhere. OpenAI's newest models are served on Responses only
and answer Chat Completions with a 400, while most OpenAI-compatible servers -
vLLM, LM Studio, a LiteLLM proxy - implement only Chat Completions. So the
choice is a field on the profile, under **Agents → add a model → API**, and the
form starts on the default:

| Profile | Default |
|---|---|
| `openai`, no endpoint (OpenAI's own API) | `responses` |
| `openai` with an endpoint | `chat` |
| `azure` | `chat`, because the Responses API needs a recent `api_version` and the secret may pin an older one |

The default is only where the form starts. A regional OpenAI endpoint such as
`https://eu.api.openai.com/v1` is an endpoint that serves Responses, so pick it
there. An omitted choice is stored as its default, so changing the default
later does not move an existing profile.

**A Responses profile does not keep conversations with OpenAI.** The Responses
API stores each response on OpenAI's side unless told not to, while Chat
Completions stores nothing by default, so a Responses model sends
`store: false`. Reasoning is carried between turns as encrypted content rather
than by a stored response id, so nothing needs the stored copy. A profile that
wants it sets `openai_store` to `true` in its settings.

## Providers

Twenty-eight, which is everything Pydantic AI ships that a chat profile can point
at.

There is no per-provider builder here. Pydantic AI infers the provider class and
the model wrapper from the id, and what this platform still has to know is the part
inference cannot: **which credential shape a provider wants.**

!!! info "What Custom URL means"

    The provider's SDK names an endpoint parameter, so you can point a profile at a
    gateway, a LiteLLM proxy or a model server on your own network instead of the
    vendor's public API.

    It is a field on the **profile**, not on the key. A key says what
    authenticates, an endpoint says where the request goes — so the same key can
    front a staging proxy and a production one as two profiles.

    Set it under **Agents → add a model → Endpoint**, which appears only for the
    providers marked below. Storing one for a provider that has none is refused,
    rather than accepted and dropped.

### Hosted

| Provider | id | Credential | Custom URL |
|---|---|---|---|
| OpenAI | `openai` | API key, or none | ✓ |
| Anthropic | `anthropic` | API key | ✓ |
| Google Gemini | `google` | API key | ✓ |
| OpenRouter | `openrouter` | API key |  ✓ |
| Alibaba Cloud | `alibaba` | API key | ✓ |
| Cerebras | `cerebras` | API key | |
| DeepSeek | `deepseek` | API key | |
| Fireworks AI | `fireworks` | API key | |
| GitHub Models | `github` | API key | |
| Groq | `groq` | API key | |
| Heroku AI | `heroku` | API key | ✓ |
| Mistral | `mistral` | API key | |
| Moonshot AI | `moonshotai` | API key | |
| Nebius AI Studio | `nebius` | API key | |
| OVHcloud AI Endpoints | `ovhcloud` | API key | |
| SambaNova | `sambanova` | API key | ✓ |
| Together AI | `together` | API key | |
| Vercel AI Gateway | `vercel` | API key | |
| Z.AI | `zai` | API key | |
| xAI (Grok) | `xai` | API key | ✓ (`api_host`) |
| Cohere | `cohere` | API key | |
| Hugging Face | `huggingface` | API key | ✓ |

### Self-hosted

| Provider | id | Credential | Custom URL |
|---|---|---|---|
| Ollama | `ollama` | none | ✓ |
| LiteLLM proxy | `litellm` | none | ✓ (`api_base`) |

These two are why "no credential" is a stored **kind** rather than an empty string.
A model server on your own network usually has nothing to authenticate against, and
the vault refuses an empty secret — so the resolver switches on a total set instead
of treating a missing value as a special case.

**A keyless profile needs its endpoint, and that is the only thing it needs.** The
key field goes optional as soon as one is filled in. Without an endpoint the
profile is refused: there is no public API to fall back on and nothing to
authenticate with.

!!! note "The endpoint is what marks a profile self-hosted, not `keyless`"

    `keyless` is true of `openai` as well. OpenAI-compatible servers (vLLM, LM
    Studio, a LiteLLM proxy) speak its Chat Completions API, which is why an
    `openai` profile with an endpoint defaults to it - see
    [Responses or Chat Completions](#responses-or-chat-completions).

    So "no key" alone does not distinguish a deliberate local model from a profile
    whose key was deleted — and the secret foreign key is `ON DELETE SET NULL`,
    which makes the second case ordinary. A run resolves a keyless profile only
    when it carries an endpoint; otherwise it is refused with the same "no key
    configured" message it always had.

### When the credential is not an API key

| Provider | id | Credential |
|---|---|---|
| Azure OpenAI | `azure` | key **+** endpoint **+** pinned API version |
| AWS Bedrock | `bedrock` | access key id, secret key, region, optional session token |
| Google Vertex AI | `google_cloud` | service account JSON |
| ChatGPT (Codex subscription) | `openai_codex` | a ChatGPT sign-in, stored by signing in rather than typed |

The first three are the reason a secret has a *kind* at all. A form that collected one
opaque token for Azure would collect something fillable-in-correctly that still
fails at the first run. See [secret kinds](secrets.md#kinds).

!!! note "Two ids are rewritten on the way to the SDK"

    An `openai` profile is built as `openai-chat` or `openai-responses`, and an
    `azure` one as `azure` or `azure-responses`, by the API it stores, rather than
    taking the Responses API that plain `openai` infers. See
    [Responses or Chat Completions](#responses-or-chat-completions).

    `google_cloud` is built as `google-cloud`. Neither changes what you store.

### Running on a ChatGPT subscription

`openai_codex` runs OpenAI models on the Codex backend through a ChatGPT
subscription, rather than through a metered API key. It is meant for **personal
use**: the sign-in is one person's subscription, and every run on a profile that
uses it counts against that person's ChatGPT limits.

Nobody can type the credential. You sign in with ChatGPT instead:

1. Under **Vault → add a secret** (or **Agents → add a model**, with **ChatGPT
   (Codex subscription)** selected), choose **Sign in with ChatGPT**. A ChatGPT
   sign-in opens in a new tab.
2. Approve it. ChatGPT then sends the browser to `http://localhost:1455/...`,
   which does not load. That is expected: OpenAI pins that address for every
   client other than its own.
3. Copy the whole address from the address bar and paste it back into the form.

The code in that address works once, only for the person who started the
sign-in, and only within 15 minutes.

The access token expires and is refreshed while models run. Each refresh spends
the refresh token, so the new pair is sealed back into the same vault secret
straight away. Two runs refreshing at the same moment can still race. The one
that loses is refused, and the fix is **Reconnect** on the secret, which signs in
again without changing its id.

!!! warning "What a ChatGPT sign-in is not"

    - **It is not the Codex CLI's `auth.json`.** That file holds the CLI's own
      grant. Refresh tokens are single-use, so whichever of the two refreshed
      first would sign the other out.
    - **It is not an organization credential.** A secret is created private by
      default, and a model on it runs only for somebody who may see the sign-in in
      the vault and is asking themselves. For anybody else - a visitor on a public
      page or an embed, a caller with an API key - and for background work such as
      describing a document's images, the model is refused, and a fallback on it is
      skipped.
    - **The spend shown is not your bill.** A run is priced at the OpenAI API
      rates for the same model, which is what a [budget](governance.md#budgets)
      can reason about. The subscription itself is billed by OpenAI at a flat rate.
    - **Some settings are ignored.** The Codex backend drops `max_tokens`,
      `temperature` and `top_p`.

### Deliberately absent

Four names Pydantic AI knows are not here. `sentence-transformers` and `voyageai`
are embedding models, `bedrock-mantle` is not a chat provider a profile can point
at, and `gateway` does not resolve to a provider class — it is a routing prefix
over the others.

`tests/test_model_profiles.py` constructs every entry in the catalog, so a provider
cannot be selectable in the Builder without being constructible at run time.

## Which list answers which question

Six things in this repository know something about models and providers, and they
are **not** six copies of one list. Each answers a different question, and the one
they are all derived from is the first:

| Ask | Answered by |
|---|---|
| Which providers may a profile point at, and what credential does each want? | `PROVIDERS` in `backend/app/agents/model_resolver.py` — **the source of truth**, and only for the part model inference cannot know |
| How do I construct the client? | `pydantic_ai`'s own `infer_provider_class` / `infer_model`. Not this platform's business, and deliberately not restated here |
| How do I read this provider's live model list? | `backend/app/core/catalog/model_listings.json` |
| What do I suggest when the provider cannot be asked? | `backend/app/core/catalog/curated_models.json` |
| What does this model cost, and how much context does it take? | the `genai-prices` snapshot, through `model_catalog.priced_model` |
| Which models draw images? | `backend/app/core/catalog/image_models.json`, plus the SDK's own answer about which providers can draw at all |

!!! info "Everything below the first row is derived from it"

    A derived copy that drifts fails nothing at run time. It shows a picker for a
    provider that does not exist, or leaves out one that does.

    `tests/test_model_catalog.py::TestOneAnswerPerQuestion` is what makes that a
    failing build instead — and it requires every provider to appear on **this
    page**.

Every key in either catalog file has to name a provider `PROVIDERS` has. So does
every entry in the image catalog. And every provider has to appear on this page.
Adding the twenty-ninth is one edit plus whatever that test then asks for.

Two crossings are worth knowing about, because they are lookups that can answer
nothing:

- The price snapshot spells four providers differently — `xai` is `x-ai`,
  `bedrock` is `aws`, `google_cloud` is `google`, and `openai_codex` is priced as
  `openai` — and `_PRICE_PROVIDER_ALIASES` bridges them.
- The image catalog carries its own `provider` and `prefix` pair, which is a third
  vocabulary again.

## Which models a provider offers

The model-id field is populated from two sources, in this order — and from neither,
for seven providers, which the answer says out loud.

### Live

Twenty providers publish a list endpoint, and it is the only source that knows
about a model released this morning:

`anthropic`, `openai`, `google`, `openrouter`, `groq`, `mistral`, `together`,
`cohere`, `deepseek`, `xai`, `sambanova`, `vercel`, `ovhcloud`, `huggingface`,
`cerebras`, `fireworks`, `nebius`, `moonshotai`, `zai`, `alibaba`.

The response shapes disagree — the array sits at `data`, at `models` or at the
document root; the id is `id`, `name` or `model`; Gemini prefixes it with
`models/` — so each is described by data rather than by a branch. Cached in-process
for an hour; these lists move on the order of weeks.

**Five of them need no credential at all** — `openrouter`, `sambanova`, `vercel`,
`ovhcloud` and `huggingface` — which is what makes them worth having: the picker
fills in before anybody has stored a key for that provider. The other fifteen are
asked with the organization's own key when there is one.

Six providers still publish nothing this can read: `github` (its catalog path is
gone), `heroku`, `azure`, `bedrock`, `google_cloud`, and a `litellm` proxy whose
list is whatever the deployment put behind it. `ollama` answers on the deployment's
own network rather than at a fixed host, so it is not listed either.

!!! warning "An empty modality list means *not stated*, never 'text only'"

    `openrouter` and the Hugging Face router both carry
    `architecture.output_modalities`, and a listing entry may name that path.
    Nobody else states it.

    A client filtering on it must treat absence as unknown, or it hides models that
    work. It is metadata a client may narrow on; it is *not* how the image
    capability picks its models, which is a catalog file plus the SDK's own answer
    about which providers can draw at all — see
    [Image generation](reference/capabilities.md#image-generation).

### Curated

A short list per provider, used when the provider publishes nothing, when the call
fails, or when there is no key to make it with.

It lives in `backend/app/core/catalog/curated_models.json` beside the other
deployment catalogs, so adding a model is one entry rather than a Python edit — and
the listings themselves are `model_listings.json` in the same directory, which is
what makes a new provider's endpoint data too.

It is deliberately short, and deliberately **not** taken from `genai-prices`, which
is already a dependency and does list models.

That is a *price* dataset. It carries `ada` and `babbage` under OpenAI, `claude-2`
under Anthropic, 690 rows under OpenRouter, and it marks almost nothing deprecated
— sorted alphabetically, the first thing a picker would offer for OpenAI is `ada`.
A short current list beats a long misleading one.

What the library *is* used for is the half that rots. **Every context length comes
from the snapshot at read time**, so no window is written down here; two that were
had already gone stale, one of them recorded twice with two different figures.

And a curated id the snapshot has never heard of fails the test suite, which is how
a typo or a retired model is caught rather than shipped as a dropdown the provider
answers 404 to. A model the snapshot knows but does not price simply has no window,
which is the null described below.

| Provider | Curated ids |
|---|---|
| `anthropic` | `claude-opus-5`, `claude-sonnet-5`, `claude-fable-5`, `claude-haiku-4-5` |
| `openai` | `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.3-codex` |
| `openai_codex` | the same four as `openai` |
| `google` | `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-pro-preview` |
| `deepseek` | `deepseek-v4-pro`, `deepseek-v4-flash` |
| `xai` | `grok-4.5`, `grok-4.3` |
| `groq` | `openai/gpt-oss-120b`, `llama-3.3-70b-versatile` |
| `openrouter` | five common cross-provider ids |

### Neither, and it says so

Seven providers publish no listing this platform can read and have no curated entry
— `github`, `heroku`, `ollama`, `litellm`, `azure`, `bedrock` and `google_cloud`.

The response's `source` is `unlisted` for those, **not** `curated`. An empty
shortlist is not a shortlist, and claiming one is what turns "this platform cannot
enumerate this provider" into "this provider has no models" (#923). The picker asks
for the id instead.

`ollama` and `litellm` are the ones worth wiring — both publish an OpenAI-shaped
`/v1/models` at the endpoint the profile already stores — and that needs the
listing to be told a base URL, which a fixed `ListingSpec.url` cannot be.

Neither source is authoritative, which is why the field stays free text.

## The window a model accepts is read once and kept

A listing usually carries how many tokens the model accepts, and the profile
records it as `context_length` when it is created.

That number is what [context management](reference/capabilities.md#context-management)
triggers on: compacting at a fraction of the window is the only setting that stays
right when an agent moves to another model.

!!! danger "Why it is stored rather than resolved per run"

    The request path must not call a provider, and the only thing it could
    otherwise consult is the bundled price snapshot — which is wrong here in the
    direction that breaks a run.

    That snapshot records 1,000,000 for `anthropic:claude-sonnet-4-5` against a
    real 200,000, so a trigger at 90% lands above the real ceiling and compaction
    never fires before the provider refuses the request. A profile with fallbacks
    is worse: it builds a `FallbackModel` whose composite id resolves to nothing at
    all.

Null means **not recorded**, not zero: a profile older than the column, a provider
that publishes no length, a curated list, or a listing that could not be reached.
The capability then resolves the window itself, exactly as it did before.

If you know better than both, set `context_window` on the binding. A provider
publishes the maximum a model *can* be made to accept, and a beta- or tier-gated
deployment gets less.

A chain of fallbacks carries the **primary's** number. A `FallbackModel` has no
window of its own, and which model a run reaches is not known until one has refused.

## What a run costs

Prices come from a bundled
[`genai-prices`](https://github.com/pydantic/genai-prices) snapshot. Nothing phones
home for them, which means two things worth knowing:

- A model too new for the snapshot is **unpriced**, and a run containing one is
  recorded as *partially priced* rather than as costing nothing. A budget that
  silently treated an unknown model as free would be a budget with a hole in it.
- An aggregator's `vendor/model` the snapshot does not list is priced as the
  vendor's own model, with a dotted version also tried with dashes:
  OpenRouter's `anthropic/claude-sonnet-5.5` costs what Anthropic's
  `claude-sonnet-5-5` does.
- Updating prices is a dependency bump.

!!! warning "A keyless provider records no spend"

    Spend is attributed to the [vault secret](secrets.md) the run resolved to, and
    a keyless provider has none to attribute it to.

Cost is checked *before* each model request and recorded even when the run fails.
See [Budgets](governance.md#budgets).

### A delegation resolves its own profile

One run can involve several models.

A [delegate](concepts.md#delegate-vs-inline-specialist) runs on the profile *its
own* spec names, resolved when the runner walks the delegation tree. An inline
specialist that names none runs on the profile of the agent that called it — both
the least surprising answer and the only one that works when the parent's is the
only profile the author chose.

Those requests are metered against the parent run's single ledger, but they are
**priced per provider**: the delegate's guard shares the ledger, the caps and the
month's baselines, and takes its own provider.

Sharing the parent's outright would price an Anthropic delegate against OpenAI's
catalog — silently, and usually as unpriced, which under-reports the run and flags a
perfectly priceable one as a floor.

The child run row a delegation writes names the model that answered it, so the cost
dashboard groups a delegated turn under the model that actually ran rather than
under the parent's.

## Realtime models

A [voice call](voice.md) does not use a model profile. Its model is a pick from
a catalog this deployment ships, `backend/app/core/catalog/realtime_models.json`,
read by `backend/app/services/realtime_models.py` and served to the Builder at
`GET /api/v1/providers/realtime-models`. The key is named on the agent's Voice
section as a vault secret, not on a profile. That is the same shape speech to
text uses: a catalog pick plus an explicit key.

Each entry names a provider, its models, and for each model:

| Field | What it decides |
|---|---|
| `transport` | `webrtc` (the browser talks to the provider; this deployment holds a sideband) or `relay` (the audio passes through this deployment's socket) |
| `input_sample_rate`, `output_sample_rate` | The PCM rates the browser records and plays at, over the relay |
| `voices`, `default_voice` | What the Voice section offers, and what an empty choice means |
| `supports_thinking` | Whether the agent's thinking capability maps onto the model's own reasoning setting |
| `context_window` | Where a reconnect switches from replaying the turns to a summary of the older ones |
| `pricing` | `kind` (`tokens` or `per_minute`), `worst_case_usd_per_minute` for the check before a call, and `usd_per_minute` for a per-minute model |

OpenAI's `gpt-realtime` family runs over WebRTC and is the only provider tested
live. Azure OpenAI, Gemini Live and xAI run over the relay and are **not
verified live**. GPT-Live is not in the catalog: it cannot take history after a
session starts, so a reconnect could not continue a call.

**Azure is a deployment plus a base model.** A deployment's name is chosen by
its owner and says nothing about what it runs, so the Voice section takes the
deployment name as free text and the catalog model it runs as `base_model`. The
base model decides the voices and the price: an Azure call's tokens are priced
as that model on OpenAI. The endpoint and API version come from the
`azure_openai` secret.

**Prices.** Token-priced models are priced per response from the same bundled
snapshot as text runs. A per-minute model (xAI) is billed for connected time at
the catalog's `usd_per_minute`. A token-priced model the snapshot cannot price
is refused when a call starts, rather than run with a budget it cannot enforce.

## Recap

- A **profile** is a named model plus a named key, and agents point at profiles so
  that rotating either touches one row.
- **28 providers**, and the only thing this platform knows about each is the
  credential shape — construction is Pydantic AI's job.
- The model id is **free text**, because no list is authoritative.
- **Context length** is read once and stored, because the price snapshot is wrong
  about it in the direction that breaks a run.
- **Cost** comes from a bundled snapshot, an unknown model is recorded as unpriced
  rather than free, and a keyless provider records no spend at all.
- **Realtime models** for voice calls are a catalog pick plus a named key, with
  no profile; only OpenAI's are verified live.

## Setting one up

The [first-agent walkthrough](first-agent.md) does this end to end. In short: store
a provider key under **Settings → Secrets**, add a model profile naming it, then
point an agent's spec at the profile.

```bash
make platform-bootstrap BOOTSTRAP_API_KEY=sk-...
```

does all three for a new deployment.

For a regional OpenRouter API, keep **OpenRouter** as the provider and set **Endpoint** to `https://eu.openrouter.ai/api/v1` in the model form. The profile keeps its OpenRouter vault key, native model handling and cache controls. Model suggestions come from that endpoint and are cached separately; a failed regional listing does not fall back to the global catalog. For knowledge bases, set the embedding **Endpoint** separately when creating the collection or editing its embedding provider. Existing configurations keep the global endpoint. EU routing requires an eligible OpenRouter Business or Enterprise plan; [regional routing](https://openrouter.ai/docs/guides/get-started/sovereign-ai) and ZDR are separate OpenRouter policies.

Upgrade every API and worker process before configuring regional endpoints. Earlier builds ignore the OpenRouter endpoint override.

For another endpoint with the same provider and model, choose **Add separate model** in the Builder. Its automatic name includes the endpoint, and the existing profile stays unchanged. **Update model** edits the shared profile instead. Custom catalog downloads are limited to 2 MiB, 2,048 models and bounded field lengths, with at most 16 catalogs cached per process. A compressed or oversized response leaves the model ID editable without falling back to a global listing.
