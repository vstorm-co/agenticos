# Models and providers

The template this platform grew from built one model from environment variables.
That stops working the moment several organizations share a deployment: each needs
its own key, its own default, and the ability to rotate either without a redeploy.

So a model is constructed **per run**, out of the database:

```
model profile → credential → unsealed secret → provider client → Model
```

Nothing about which model an agent uses lives in `.env`. `configuration.md` says
the same thing in one line under *AI Models*, and this page is the long version.

## A model profile

A row in an organization: a label, a provider, a model id, default settings, and
which [vault secret](secrets.md) to authenticate with. An agent's spec names one by
`model_profile_id`, and the run resolves it.

The model id is **free text**, deliberately, with a picker to help. A provider
ships something the morning after any list here was warmed, and a field that
cannot express "that one" is a field people work around by editing the spec by
hand.

### Fallbacks

A profile may list fallback profiles, tried in order. One provider's outage should
not take an organization's agents down when it has a second key or a second
provider configured.

!!! warning "A fallback is invisible in the run record"

    A run row is written before the first request, carrying the **primary**
    profile's label, provider and secret id. If a fallback served the turn, the run
    still names the primary — so "what did we spend at OpenAI" and "which key is
    costing the most" answer with the profile that was *asked* first, not the one
    that answered. Worth knowing before you rely on those numbers during an
    outage.

### Model settings

Per profile, and overridable per agent through the spec's `model_settings`:
`temperature`, `top_p`, `max_tokens`, `parallel_tool_calls`, `timeout`. See
[the spec reference](reference/spec.md#model-settings).

Reasoning effort is *not* here. It is the [`thinking`
capability](reference/capabilities.md#thinking), because "reason harder" is a
decision about what the agent is for, not a knob on a connection — and because a
spec that sets it as a model setting stops being portable across a model swap.

## Providers

Twenty-seven, which is everything Pydantic AI ships that a chat profile can point
at. There is no per-provider builder: Pydantic AI infers the provider class and
the model wrapper from the id. What this platform still has to know is the part
inference cannot — **which credential shape a provider wants**.

**Custom URL** means the provider's SDK names an endpoint parameter, so a profile
may be pointed at a gateway, a LiteLLM proxy or a model server on your own network
instead of the vendor's public API. It is a field on the **profile**, not on the
key: a key says what authenticates, an endpoint says where the request goes, so the
same key can front a staging proxy and a production one as two profiles.

Set it under **Agents → add a model → Endpoint**, which appears only for the
providers marked below. Storing one for a provider that has none is refused rather
than accepted and dropped.

### Hosted

| Provider | id | Credential | Custom URL |
|---|---|---|---|
| OpenAI | `openai` | API key, or none | ✓ |
| Anthropic | `anthropic` | API key | ✓ |
| Google Gemini | `google` | API key | ✓ |
| OpenRouter | `openrouter` | API key | |
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

These two are why "no credential" is a stored *kind* rather than an empty string.
A model server on the deployment's own network usually has nothing to authenticate
against, and the vault refuses an empty secret — so the resolver switches on a
total set instead of treating a missing value as a special case.

**A keyless profile needs its endpoint, and that is the only thing it needs.** The
key field goes optional as soon as one is filled in; without an endpoint the profile
is refused, because there is no public API to fall back on and nothing to
authenticate with.

!!! note "The endpoint is what marks a profile self-hosted, not `keyless`"

    `keyless` is true of `openai` as well — OpenAI-compatible servers (vLLM, LM
    Studio, a LiteLLM proxy) speak its Chat Completions API, which is why an
    `openai` profile is built as `openai-chat`. So "no key" alone does not
    distinguish a deliberate local model from a profile whose key was deleted, and
    the secret foreign key is `ON DELETE SET NULL`, which makes the second case
    ordinary. A run resolves a keyless profile only when it carries an endpoint;
    otherwise it is refused with the same "no key configured" message it always
    had.

### Credential is not an API key

| Provider | id | Credential |
|---|---|---|
| Azure OpenAI | `azure` | key **+** endpoint **+** pinned API version |
| AWS Bedrock | `bedrock` | access key id, secret key, region, optional session token |
| Google Vertex AI | `google_cloud` | service account JSON |

These three are the reason a secret has a *kind* at all. A form that collected one
opaque token for Azure would collect something fillable-in-correctly that still
fails at the first run. See [secret kinds](secrets.md#kinds).

!!! note "Two ids are rewritten on the way to the SDK"

    An `openai` profile is built as `openai-chat`, because plain `openai` infers
    the Responses API and OpenAI-compatible servers — vLLM, LM Studio, a LiteLLM
    proxy — do not implement it. `google_cloud` is built as `google-cloud`.
    Neither changes what you store.

### Deliberately absent

Four names Pydantic AI knows are not here. `sentence-transformers` and `voyageai`
are embedding models, `bedrock-mantle` is not a chat provider a profile can point
at, and `gateway` does not resolve to a provider class — it is a routing prefix
over the others.

`tests/test_model_profiles.py` constructs every entry in the catalog, so a
provider cannot be selectable in the Builder without being constructible at run
time.

## Which models a provider offers

The model-id field is populated from two sources, in this order.

**Live.** Twenty providers publish a list endpoint, and it is the only source that
knows about a model released this morning: `anthropic`, `openai`, `google`,
`openrouter`, `groq`, `mistral`, `together`, `cohere`, `deepseek`, `xai`,
`sambanova`, `vercel`, `ovhcloud`, `huggingface`, `cerebras`, `fireworks`,
`nebius`, `moonshotai`, `zai`, `alibaba`. The response shapes disagree — the array
sits at `data`, at `models` or at the document root; the id is `id`, `name` or
`model`; Gemini prefixes it with `models/` — so each is described by data rather
than by a branch. Cached in-process for an hour; these lists move on the order of
weeks.

**Five of them need no credential at all** — `openrouter`, `sambanova`, `vercel`,
`ovhcloud` and `huggingface` — which is what makes them worth having: the picker
fills in before anybody has stored a key for that provider. The other fifteen are
asked with the organization's own key when there is one.

Six providers still publish nothing this can read: `github` (its catalog path is
gone), `heroku`, `azure`, `bedrock`, `google_cloud` and a `litellm` proxy, whose
list is whatever the deployment put behind it. `ollama` answers on the deployment's
own network rather than at a fixed host, so it is not listed here either.

**What a model emits, where the provider says so.** `openrouter` and the Hugging
Face router both carry `architecture.output_modalities`, and a listing entry may
name that path; nobody else states it. An empty list means *not stated*, never
"text only" — a client filtering on it must treat absence as unknown, or it hides
models that work. This is how "which models draw an image" can be answered at all
without guessing from a model's name.

**Curated.** A short hand-kept list per provider, used when the provider publishes
nothing, when the call fails, or when there is no key to make it with. Deliberately
small — the five or six somebody would actually pick, not a mirror of a catalog:

| Provider | Curated ids |
|---|---|
| `anthropic` | `claude-opus-5`, `claude-sonnet-5`, `claude-fable-5`, `claude-haiku-4-5` |
| `openai` | `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.3-codex` |
| `google` | `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-pro-preview` |
| `deepseek` | `deepseek-v4-pro`, `deepseek-v4-flash` |
| `xai` | `grok-4.5`, `grok-4.3` |
| `groq` | `openai/gpt-oss-120b`, `llama-3.3-70b-versatile` |
| `openrouter` | five common cross-provider ids |

Neither source is authoritative, which is why the field stays free text.

### The window a model accepts is read once and kept

A listing usually carries how many tokens the model accepts, and the profile
records it as `context_length` when it is created. That number is what
[context management](reference/capabilities.md#context-management) triggers on:
compacting at a fraction of the window is the only setting that stays right when
an agent moves to another model.

It is stored rather than resolved per run, because the request path must not call
a provider and the only thing it could otherwise consult is the bundled price
snapshot — which is wrong here in the direction that breaks a run. That snapshot
records 1,000,000 for `anthropic:claude-sonnet-4-5` against a real 200,000, so a
trigger at 90% lands above the real ceiling and compaction never fires before the
provider refuses the request. A profile with fallbacks is worse: it builds a
`FallbackModel` whose composite id resolves to nothing at all.

Null means **not recorded**, not zero: a profile older than the column, a provider
that publishes no length, a curated list, or a listing that could not be reached.
The capability then resolves the window itself, exactly as it did before. An
author who knows better than both sets `context_window` on the binding — a
provider publishes the maximum a model *can* be made to accept, and a beta- or
tier-gated deployment gets less.

A chain of fallbacks carries the **primary's** number. A `FallbackModel` has no
window of its own, and which model a run reaches is not known until one has
refused.

## What a run costs

Prices come from a bundled [`genai-prices`](https://github.com/pydantic/genai-prices)
snapshot. Nothing phones home for them, which means two things worth knowing:

- A model too new for the snapshot is **unpriced**, and a run containing one is
  recorded as partially priced rather than as costing nothing. A budget that
  silently treated an unknown model as free would be a budget with a hole in it.
- Updating prices is a dependency bump.

Spend is attributed to the [vault secret](secrets.md) the run resolved to — which
is why a keyless provider records none: there is no key to attribute it to. Cost
is checked *before* each model request and recorded even when the run fails. See
[Budgets](governance.md#budgets).

### A delegation resolves its own profile

One run can involve several models. A [delegate](concepts.md#delegate-vs-inline-specialist)
runs on the profile *its own* spec names, resolved when the runner walks the
delegation tree; an inline specialist that names none runs on the profile of the
agent that called it, which is both the least surprising answer and the only one
that works when the parent's is the only profile the author chose.

Those requests are metered against the parent run's single ledger, but they are
**priced per provider**: the delegate's guard shares the ledger, the caps and the
month's baselines, and takes its own provider. Sharing the parent's outright would
price an Anthropic delegate against OpenAI's catalog — silently, and usually as
unpriced, which under-reports the run and flags a perfectly priceable one as a
floor.

The child run row a delegation writes names the model that answered it, so the cost
dashboard groups a delegated turn under the model that actually ran rather than
under the parent's.

## Setting one up

The [first-agent walkthrough](first-agent.md) does this end to end. In short:
store a provider key under Settings → Secrets, add a model profile naming it, then
point an agent's spec at the profile. `make platform-bootstrap
BOOTSTRAP_API_KEY=sk-...` does all three for a new deployment.
