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

## Personal model keys

In the Builder's **Model access**, keep **Use the organization’s key** (the default), or select **Each user connects their own key**. Personal mode keeps the administrator's model and endpoint fixed. It supports API-key chat providers, without model fallbacks or per-conversation model overrides.

A signed-in member opens the agent in web chat and connects their key through the private form above the composer or in chat controls. Keys never enter messages, prompts or agent instructions. The same connection is reused across agents in this organization with the same provider and endpoint. A missing key blocks the run before a model request; authentication errors never switch to the organization's key. Replace the key in chat settings, or remove the connection in **Vault → Your model connection**. Saving a key does not test it against the provider.

The private-key form submits the expected profile, provider, endpoint and model shown to the user. If that destination changes before saving, the server refuses the key with a conflict; the form reloads the destination and clears the typed key before another attempt.

Personal mode currently excludes channels (private and group), widgets, hosted pages, HTTP API runs, schedules, triggers, background topics, voice, reviewers and separate capability models. Pause or remove active channels, public surfaces and routines before publishing this mode. Creating or reactivating an incompatible surface is refused, and the runtime enforces the same rule. Hosted pages and widget JWTs do not identify a signed-in member of the instance.

Delegation is supported in signed-in web chat. A personal-mode subagent must use the exact model profile selected on a personal-mode root agent. Organization-mode parents cannot spend personal keys, and personal delegates cannot select another model or endpoint. These limits are checked at publication, surface admission, promotion and runtime, including nested delegations and approval resumes.

Organization-mode delegates retain their own credentials. Inline specialists inherit their parent's mode; dynamic specialists in personal mode stay on their parent's configured model. Personal MCP access keeps its existing caller boundaries.

A missing subagent connection names the agent and model connection. Open that agent's chat settings to connect your key; ask its owner for access if it is not visible. The runner checks the delegation tree before model calls and checks again on resume. A key for another endpoint, another member's key or an approver's key never substitutes for the caller's missing connection.

Credentials are encrypted for their owner in the vault, and are deleted when their membership or user account is removed. Changing the approved endpoint requires a new connection. Rotating one member's key does not change another member's key or the shared model profile.

Impersonating another member never grants access to their personal model connections: requests to inspect, change or use their key are refused before vault access.

Private conversation history follows the approved model destinations, including fallbacks; see [chat history](console.md#chat) for switching connections and resuming waiting runs.

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

### The model a new agent starts on

There is no organization-wide default model. An agent's spec names its model,
and publish refuses a spec that names none.

A new agent that names no model starts on the organization's model when the
organization has exactly one model an agent can run on. That is a chat model with a
key, or a self-hosted one saved to run without a key, which publish accepts as it
stands, fallbacks included. It applies to every way of creating an agent: **New
agent** in the console, `POST /agents` without a `model_profile_id`, a template, a
copy of a draft that has no model, and a promoted specialist.

The Architect, the organization's assistant, chooses its own model when it
publishes: the first chat model that publish accepts, and never a model on a
[ChatGPT sign-in](#running-on-a-chatgpt-subscription). The Architect serves the
whole organization, and a sign-in is one person's subscription: runs by members who
may not see it in the vault are refused, and runs by those who may, such as the
organization's owners and admins, spend it. With only a sign-in, the Architect waits
for another model.

A sign-in somebody picks in its draft, or a model that falls back to one, stays
there, but is published only when somebody who may change the organization's
settings publishes it in the Builder. An
Architect already published on a sign-in keeps that model until somebody who may
change the organization's settings picks another under **Build > Model** and
publishes it.

The model is written into the draft, so the agent publishes without anybody opening
**Model**, and its history shows which model it was published on. A spec that names
a model keeps it. The draft then counts as using the model, so the model cannot be
deleted until the agent moves to another model or is deleted; archiving it is not
enough. To change only the model's key or endpoint, edit it in place
([Changing a profile's key or endpoint](#changing-a-profiles-key-or-endpoint)).

The draft stays without a model when the organization has none, or more than one.
Profiles that cannot run an agent do not count: a profile with no key, a
text-to-speech model and the other models in
[A profile an agent cannot run on](#a-profile-an-agent-cannot-run-on), and neither does a profile
publish would refuse, such as one that falls back to such a model. A model on
a [ChatGPT sign-in](#running-on-a-chatgpt-subscription) is never chosen for
somebody, because it is one person's subscription, but it counts as a model.

Nor is a new agent started on a model whose fallbacks include a sign-in among
the first three, the ones a run tries: when the model fails, the run of anybody
who may see the sign-in would fall back onto that subscription. The Architect
does not choose such a model either. An author may still pick one deliberately
and publish it.

Publish then refuses the draft with *No model selected - pick one under Build >
Model before publishing*. The refusal also marks the field (`model_profile_id` in
`details.fields`), and the console shows **Go to Model** beside it, which opens the
**Build** tab at the **Model** card.

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

Daily briefing, suggestions and memory maintenance expose these defaults in the
organization's model picker, together with reasoning effort. Changes are saved
explicitly to the shared model profile and affect every consumer of that profile.
Unset controls send no override; leave unsupported parameters at provider defaults.
Agents can override reasoning through the
[`thinking` capability](reference/capabilities.md#thinking), which uses Pydantic AI's
provider-neutral setting. Background roles have no agent spec and use the profile's
`thinking` default directly.

### Responses or Chat Completions

OpenAI publishes two APIs for the same models, and a profile on `openai`,
`azure` or `stav` stores which one its requests go to: `responses` or `chat`. Every other
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
| `stav` | from the model: `chat` where it is served, else `responses` |

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

### Where a Stav profile's requests run

A profile on `stav` stores a region: `eu`, `eea` or `global`. Stav answers only
from endpoints that compute in that region, fails over only inside it, and
refuses a request it cannot serve there. `global` sets no limit of its own. The region only narrows what the Stav
workspace's own policy allows.

Set it under **Agents → add a model → Region**. The form starts on `eu`, and an
omitted region is stored as `eu`, so a profile never leaves the EU unless it was
saved with `eea` or `global`.

The region is sent as the `X-Stav-Runs-In` header on every request, not in the
body, so an `extra_body` in the profile's settings cannot replace it.

Custom Stav catalogs use the vault key selected in the form. The caller must be able to see that key; the application never chooses a hidden organization key for a custom URL. Authenticated catalog caches are separated by credential. Request-level `extra_headers` cannot override the profile's EU or EEA restriction.

### Otari gateway

Select **Otari** when adding a model, save an Otari API key in the vault and select it for the profile. **Endpoint** is required: enter `https://api.otari.ai/api/v1` for hosted Otari. For an Otari EU account, set `https://eu.api.otari.ai/api/v1`; for a self-hosted gateway, use its API root ending in `/api/v1`, reachable from the API and workers.

Click **Load models** after choosing the endpoint and key. Editing either requires confirming the destination again; typing an address never sends the key.

Model suggestions come from that gateway's authenticated `/models` endpoint using the selected key. A custom endpoint requires `connections:manage` and access to that key. Catalog caches are separated by endpoint and credential; a failed custom listing never substitutes the hosted catalog. The model field also accepts a model selector such as `anthropic:claude-sonnet-4-6`, or an alias/routing policy configured in Otari.

The integration uses [`pydantic-ai-otari`](https://github.com/mozilla-ai/otari/tree/main/integrations/pydantic-ai-otari): its `OtariProvider` supplies the model-family profile to Pydantic AI's Chat Completions model, as `OtariModel` does. Requests always use Chat Completions; the form does not offer Responses or Stav's region controls. Keys and endpoints are passed explicitly from the profile, without an `OTARI_*` or `OPENAI_API_KEY` environment fallback. Otari's gateway budgets and routing are additional controls; AgenticOS still applies its own budgets and approvals.

Direct `provider:model` selectors use the upstream model's bundled catalog price for AgenticOS budgets; bare routing aliases and unknown models remain explicitly partially priced. These are upstream price estimates: use Otari's usage view for gateway charges.

## Providers

Chat providers supported by Pydantic AI, plus Otari through its integration package, Stav with its regional routing and MiniMax through its compatible API.

Standard providers use Pydantic AI's model and provider inference. The platform records credential shapes and integrates provider packages where needed.

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
| TypeSafe (Jev) | `typesafe` | API key | ✓ |
| OpenRouter | `openrouter` | API key |  ✓ |
| Otari | `otari` | API key | ✓ |
| Alibaba Cloud | `alibaba` | API key | ✓ |
| Cerebras | `cerebras` | API key | |
| DeepSeek | `deepseek` | API key | |
| Fireworks AI | `fireworks` | API key | |
| GitHub Models | `github` | API key | |
| GitHub Copilot | `github_copilot` | account token / personal sign-in | |
| Groq | `groq` | API key | |
| Heroku AI | `heroku` | API key | ✓ |
| LLMTR | `llmtr` | API key | |
| Mistral | `mistral` | API key | |
| MiniMax | `minimax` | API key | ✓ |
| Kimi Code (plan) | `kimi_code` | API key | ✓ |
| Alibaba Coding Plan | `alibaba_coding_plan` | API key | ✓ |
| OpenCode Go | `opencode_go` | API key | ✓ |
| Ollama Cloud | `ollama_cloud` | API key | ✓ |
| Nous Portal | `nous_portal` | API key | ✓ |
| Inception | `inception` | API key | ✓ |
| Cline | `cline` | API key | ✓ |
| Chutes | `chutes` | API key | ✓ |
| Synthetic | `synthetic` | API key | ✓ |
| CLIProxyAPI (subscription gateway) | `cliproxyapi` | API key | ✓ |
| Moonshot AI | `moonshotai` | API key | |
| Nebius AI Studio | `nebius` | API key | |
| OVHcloud AI Endpoints | `ovhcloud` | API key | |
| SambaNova | `sambanova` | API key | ✓ |
| Stav.ai | `stav` | API key | ✓ |
| Together AI | `together` | API key | |
| Vercel AI Gateway | `vercel` | API key | |
| Z.AI | `zai` | API key | ✓ |
| xAI (Grok) | `xai` | API key | ✓ (`api_host`) |
| Cohere | `cohere` | API key | |
| Hugging Face | `huggingface` | API key | ✓ |

LLMTR lists only models advertising `CHAT_COMPLETIONS`. A model without a reviewed price in the bundled snapshot can run only without an active dollar ceiling; its cost remains marked incomplete. A budgeted run also refuses further LLMTR calls when earlier usage has an unknown cost.

Select **MiniMax** for its OpenAI-compatible Chat Completions API. Store your M Plan API key as a MiniMax vault key; a metered API key uses its own billing instead. An empty Endpoint uses `https://api.minimax.io/v1`; set a custom Endpoint only for the region or gateway your key belongs to. Enter the exact model ID from your account, for example `MiniMax-M3.1-Flash`; this integration does not enumerate a plan-specific catalog. MiniMax history has its own provider identity, so OpenAI encrypted reasoning is not sent to it. Token prices, when known, are budget estimates rather than your subscription bill.

For a **Z.AI GLM Coding Plan**, select **Z.AI** and explicitly set **Endpoint** to `https://api.z.ai/api/coding/paas/v4` (global) or `https://open.bigmodel.cn/api/coding/paas/v4` (China), using a key for that plan and region. Leaving Endpoint empty keeps the ordinary metered API; existing profiles do not change.

**Subscription plan keys.** Four more providers bill a subscription plan through a plan key for an OpenAI-compatible endpoint. Store the plan's key under the matching vault purpose; the model list comes from that key's own catalog, and an empty Endpoint uses the plan's default.

| Provider | Default endpoint | Other region or note |
|---|---|---|
| Kimi Code (plan) | `https://api.kimi.ai/coding/v1` | China: `https://api.kimi.com/coding/v1` |
| Alibaba Coding Plan | `https://coding-intl.dashscope.aliyuncs.com/v1` | China: `https://coding.dashscope.aliyuncs.com/v1` |
| OpenCode Go | `https://opencode.ai/inference/go/openai/v1` | Models not served over this protocol are refused by the endpoint |
| Ollama Cloud | `https://ollama.com/v1` | Cloud models of your Ollama account |

A plan key is not interchangeable with the vendor's metered API key. Some vendors restrict plan keys to coding tools; using one from an agent platform is your decision and may limit or suspend the plan. AgenticOS budgets treat this usage as unpriced subscription use.

**More OpenAI-compatible accounts.** Nous Portal, Inception, Cline, Chutes and Synthetic take the key from that service's own console. An empty Endpoint uses its default below, and the model list comes from the key's catalog. Nous Portal, Chutes and Synthetic subscriptions are treated as unpriced; Cline credits and Inception usage are priced only where AgenticOS knows the model's price.

| Provider | Default endpoint |
|---|---|
| Nous Portal | `https://inference-api.nousresearch.com/v1` |
| Inception | `https://api.inceptionlabs.ai/v1` |
| Cline | `https://api.cline.bot/api/v1` |
| Chutes | `https://llm.chutes.ai/v1` |
| Synthetic | `https://api.synthetic.new/openai/v1` |

**Your own CLIProxyAPI gateway.** Accounts whose vendors offer no plan key (Antigravity, Grok Build, Devin, Muse Code, Kimi Code sign-in and others) can also be used through a [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) gateway that you or your operator run outside the stack. [Subscription accounts](#subscription-accounts) are the same idea built in, with each person's accounts kept apart. Sign the accounts in to the gateway with its own login commands, add a client key under `access.api-keys`, then create a **CLIProxyAPI (subscription gateway)** profile with its Endpoint (for example `http://cliproxyapi:8317/v1` for a gateway container on the deployment's network) and that client key. Every account the gateway holds is available to whoever can use the profile, so run a personal gateway for a personal account. Add the gateway's host to `OUTBOUND_PRIVATE_ALLOWLIST`; loopback addresses are never reachable from the server. Vendors may limit or suspend accounts used this way; that risk is the account owner's.

Choose the vault key and confirm the destination before loading models. A custom catalog uses that key and endpoint only; an unavailable listing leaves the model field editable rather than substituting the general API catalog. AgenticOS budget estimates do not measure your remaining subscription allowance.

### Subscription accounts { #subscription-accounts }

In the agent editor and chat model picker, start with **Your subscriptions**, choose a familiar provider such as **Claude Code (Pro, Max)** or **ChatGPT (Codex)**, then **Connect**. Sign-in opens in place and returns to the model picker; the list comes from that vendor's connected accounts, not a guess based on model names. Unavailable accounts offer **Reconnect**. You can still manage and disconnect accounts under **Settings → Subscriptions**. Organization API keys are a separate group; manually configured gateways and endpoints are under **Advanced / custom endpoint**. Existing `subscription_accounts` and `cliproxyapi` profiles keep their API IDs.

Chat catalogs show every chat-capable entry rather than silently stopping at 100. The picker shows the number of choices, whether the catalog is live or a limited fallback, and a refresh action. OpenRouter shows its current catalog region; changing it is explicit and preserves that region when saving the new model. Saved models keep their own connection settings.

During onboarding, **Which subscriptions do you already have?** lets people select their existing plans and sign in before their first chat. This is optional and available to members; these accounts remain personal and do not configure the organization’s shared starter model.

When several personal accounts are connected, open the **Account** tab and choose the account, just as you choose a stored API key. Subscription models use the same searchable list as API providers; selecting a model applies it immediately. Applying a model binds it to that account using an opaque route; it does not silently switch to another account. Account-specific profiles require the caller to have that account connected. The picker restores the account and model when reopened, and keeps account routing out of display names.

**Settings → Subscriptions** lists each connected account separately, with quota windows, remaining percentages, progress bars and reset times. The model picker’s **Account** tab uses the same view for every account of the selected provider.

Claude, Codex, Antigravity and both Kimi Code regions read quota metadata without making an inference request. Claude includes five-hour, weekly and model-family windows. Antigravity preserves separate model groups; Kimi preserves weekly and rolling windows. Devin shows reported daily and weekly snapshots. Grok and Meta allowance reads are not available through this gateway connection.

Usage refreshes every minute while visible, or every five minutes for Claude, and can be refreshed manually. Older observations are marked stale. Failed reads remain explicit; missing quota data never becomes a full allowance. Kimi Code (kimi.com) and Kimi Code (kimi.ai) are separate regional sign-ins; neither entry represents a consumer-chat plan.

All connection groups are visible immediately. Connected subscriptions show a status badge and account identity; adding another account is a secondary action. Reopening the picker restores the subscription source and model from the saved subscription profile.

Subscription models use the AgenticOS instructions and tools in the Pydantic AI runtime. They do not launch Claude Code or another coding harness. In Capabilities, **Delegate to agents** groups subagents, **Claude Code & Codex** and **Other installed agents**. Coding Agent remains enabled in the default AgenticOS template. Groups follow everyday work, knowledge, research, outputs, delegation, automation and channels, with advanced tuning collapsed last. Enabled capabilities appear first within each group, followed by recommended ones.

People sign in to their own subscriptions from the console, and models on the
**Subscription accounts** provider run on them. Under **Settings → Subscriptions**, each person connects Claude (Pro, Max), ChatGPT (Codex),
Google Antigravity, Grok, Kimi, Devin or Meta AI accounts. A sign-in shows a code
to enter on the provider's page, or asks for the address the browser ended on
after approving.

A profile on this provider takes only a model id, with no key and no endpoint.
**Add model** lists the models your own accounts serve. When a person chats with
an agent on such a profile, the run uses that person's accounts and nobody
else's. A run started by an API key, a published agent's visitor or background
work has no person behind it, so it is refused. For the same reason the platform
never picks such a model for a new agent.

The `subscription-gateway` service ships with the stack and runs
[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) (MIT) once per person
per organization. It starts a person's process on first use and stops it after
ten idle minutes. Each process listens on loopback with its own keys and
sign-in directory, and the API derives which one a request reaches from the
organization and the person; a browser never names it. When a member leaves, a
background job deletes their sign-ins; deleting an organization deletes every
member's. Signing in to the same account in two organizations means signing in
twice.

Scopes also include the membership ID: rejoining creates a new scope, so
an old cleanup job cannot delete newly connected accounts. Credential deletion is
queued even while the gateway is disabled; a disabled or failing gateway leaves a
visible failed job rather than confirming deletion. Retry that job after restoring
the gateway. A failed sign-in status read shows an error and a Retry control.

Vendors may limit how a subscription is used outside their own apps and can
suspend an account for it. The console states this risk, and the account owner
accepts it. Cursor and Qwen Code have no sign-in the gateway supports, so they
are not offered. AgenticOS budgets record these runs without a price, because a
subscription's remaining allowance is not measured per token. See
[configuration](configuration.md#subscription-accounts) for running the gateway.

### Self-hosted

| Provider | id | Credential | Custom URL |
|---|---|---|---|
| System One API | `system-one` | API key, or none | ✓ |
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

### Your own endpoint

| Provider | id | Credential | Custom URL |
|---|---|---|---|
| Custom (OpenAI-compatible) | `openai_compatible` | API key | ✓ |
| Custom (Anthropic-compatible) | `anthropic_compatible` | API key | ✓ |

These two are an API *shape* rather than a vendor. You type the address of a
server you run or a gateway you trust, and the key that authenticates it. Pick
the one that matches what your endpoint answers:

| Your endpoint answers | Choose | The address to enter |
|---|---|---|
| `POST /chat/completions` — vLLM, LM Studio, a LiteLLM proxy, most gateways | `openai_compatible` | the `/v1` root, such as `https://llm.example/v1` |
| `POST /v1/messages` — Anthropic's own API shape | `anthropic_compatible` | the API root, such as `https://llm.example` |

Both need an endpoint and a key. There is no public API to fall back on, so a
profile without one is refused rather than sent somewhere else.

The key is stored in the vault under the provider's own name, which says there
that it authenticates *that* endpoint rather than a vendor's public API. That is
why they are entries of their own rather than an `openai` or an `anthropic`
profile with an endpoint: a key filed under a vendor names that vendor.

!!! info "The Anthropic address carries no `/v1`"

    Anthropic's SDK posts to `<endpoint>/v1/messages`, so the endpoint is the
    API root. An address that already ends in `/v1` is trimmed for you, so
    either spelling works — but the root is what the platform asks for.

**Load models** reads the list from the same endpoint, with the same key, so
the dropdown offers what your server actually serves. The model id stays free
text: a server that publishes no list can still be used by typing the id.

### When the credential is not an API key

| Provider | id | Credential |
|---|---|---|
| Azure OpenAI | `azure` | key **+** endpoint **+** pinned API version |
| AWS Bedrock | `bedrock` | access key id, secret key, region, optional session token |
| Google Vertex AI | `google_cloud` | service account JSON |
| ChatGPT (Codex subscription) | `openai_codex` | a ChatGPT sign-in, stored by signing in rather than typed |
| ChatGPT (official plan usage) | `openai_chatgpt` | an application grant with separate plan consent, created by signing in |
| Subscription accounts | `subscription_accounts` | each person's own subscription sign-ins, through the bundled gateway; no key |

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

Nobody can type the credential. You sign in with ChatGPT instead, by default
with a short code:

1. Under **Vault → add a secret** (or **Agents → add a model**, with **ChatGPT
   (Codex subscription)** selected, or **Settings → Coding accounts**), choose
   **Sign in with a code**. ChatGPT's device page opens in a new tab and the form
   shows a code.
2. Enter the code on that page and approve the sign-in. The form notices the
   approval by itself and finishes; nothing is pasted back.

The code works for 15 minutes, only for the person who started the sign-in.
If your account cannot use device codes, open **Paste an address instead**:
choose **Sign in with ChatGPT**, approve it, and copy the address ChatGPT sends
the browser to (`http://localhost:1455/...`, which does not load) back into the
form. That address also works once, only for the person who started the
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
    - **It is not anybody's to publish on.** Publishing, rolling back to or
      promoting a version of an agent is refused for somebody who cannot see the
      sign-in in the vault when a model its runs reach is on one: the agent's
      model, a reviewer's, an inline specialist's or an enabled capability's,
      the model of a [delegate it pins](reference/capabilities.md#delegation)
      and of what that delegate reaches in turn, or one of the first three
      fallbacks of any of them. The sign-in's owner, owners and admins, and
      anybody it was shared with may. An API key may not, whatever its issuer
      can see, because a run under a key never spends a sign-in. A version
      published on it earlier keeps running.
    - **It is not offered to a specialist the model invents.** Under
      [`allow_dynamic`](reference/capabilities.md#delegation) a run's model may
      pick a specialist's model from the organization's profiles. A profile on a
      sign-in, or one whose first three fallbacks reach one, is on that list only
      when the agent's spec names that exact profile as one of the models above.
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

Thirty providers publish a list endpoint, and it is the only source that knows
about a model released this morning:

`anthropic`, `openai`, `google`, `openrouter`, `groq`, `mistral`, `together`,
`cohere`, `deepseek`, `xai`, `sambanova`, `vercel`, `ovhcloud`, `huggingface`,
`cerebras`, `fireworks`, `nebius`, `moonshotai`, `zai`, `alibaba`,
`kimi_code`, `alibaba_coding_plan`, `opencode_go`, `ollama_cloud`, `cliproxyapi`, `nous_portal`,
`inception`, `cline`, `chutes`, `synthetic`.

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

The subscription picker reads the deployment’s curated list when opened. It has no live account-specific catalog. GPT-6.2 entries were checked against the Codex app server and leave context blank until the pricing snapshot records it.

| Provider | Curated ids |
|---|---|
| `anthropic` | `claude-opus-5`, `claude-sonnet-5`, `claude-fable-5`, `claude-haiku-4-5` |
| `openai` | `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.3-codex` |
| `openai_codex` | GPT-6.2 Sol and Astra, GPT-6.1 Sol and Terra, GPT-6 Sol, Astra and Luna, and the earlier Codex IDs |
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

A regional endpoint serves fewer embedding models than the global one: `eu.openrouter.ai` serves `mistralai/mistral-embed-2312`, `mistralai/codestral-embed-2505` and `google/gemini-embedding-2`, and none of OpenAI's. The create form offers only the models the endpoint lists, and a collection whose model the endpoint does not serve is refused, both when it is created and when it is moved there. The two Mistral models are not in the bundled price snapshot, so their spend is recorded as partially priced.

Upgrade every API and worker process before configuring regional endpoints. Earlier builds ignore the OpenRouter endpoint override.

For another endpoint with the same provider and model, choose **Add separate model** in the Builder. Its automatic name includes the endpoint, and the existing profile stays unchanged. **Update model** edits the shared profile instead. Custom catalog downloads are limited to 2 MiB, 2,048 models and bounded field lengths, with at most 16 catalogs cached per process. A compressed or oversized response leaves the model ID editable without falling back to a global listing.

## Decision models

Decision profiles use a native `decisions` API instead of text generation. Select the provider, model and vault key in the model builder. OpenAI, Google and OpenRouter offer both chat and decision APIs; TypeSafe and a custom System One endpoint serve decisions. A decision profile cannot be the conversational model of an agent or a fallback to a chat model.

The native adapters come from Pydantic AI. Current suggestions include OpenAI `gpt-6-luna`, Google `gemini-decision-1` and TypeSafe `jev-1.14.0` / `jev-latest`. OpenRouter reads its decision-model catalog separately from its text-model catalog. A custom System One endpoint requires its own URL and model identifier. Availability and account access depend on the provider; suggestions are not a guarantee of access.

Workflow **Decision models** steps select a native profile. Existing `decide.*` ids and TypeSafe key configurations still load. Answers below the configured confidence follow the `unsure` port. Credentials and authorization are checked again for each execution, and provider spend counts toward workflow and organization budgets.

Channel **Join conversations automatically** can use a native decision profile or an ordinary LLM with structured output. A native yes/no decision returns the probability of joining; a bounded numeric output preserves that probability. An LLM returns a usefulness assessment from 0 to 100, not a calibrated probability. Both compare against **Run the agent from (%)**, including the threshold itself. The classifier has no tools. Joining remains opt-in and uses the configured intervals; the main agent can use organization MCP accounts, never a participant's private credentials.

Provider references: [Pydantic AI](https://pydantic.dev/docs/ai/models/decision/), [OpenAI](https://developers.openai.com/api/docs/guides/decisions), [Google](https://ai.google.dev/gemini-api/docs/decisions-api), [TypeSafe](https://docs.typesafe.ai/models), [OpenRouter](https://github.com/OpenRouterTeam/skills/tree/main/skills/openrouter-decisions).

ElevenLabs Realtime adds `eleven_realtime_v1_mini` and `eleven_realtime_v1_max` over the 24 kHz PCM relay, using the `brian` default voice and semantic turn detection.

The SDK does not report token charges. Calls with a configured spending budget are refused before connecting; calls without a spending budget retain the time cap and record connected audio as a cost floor, not a full bill. The catalog audio rate is $0.08/minute ($0.16 burst); token charges are additional. The 16k context value is a conservative platform history-seeding budget, not a published vendor context window. The integration is tested offline against SDK construction and controlled transports, not live accounts. [SDK](https://pydantic.dev/docs/ai/api/realtime/elevenlabs/), [ElevenLabs API pricing](https://elevenlabs.io/pricing/api).

## GitHub Copilot accounts { #github-copilot-accounts }

**GitHub Copilot** (`github_copilot`) uses Pydantic AI's Copilot model dialect, distinct from GitHub Models (`github`). It sends explicit vault credentials to the fixed `https://api.githubcopilot.com` gateway, with AgenticOS integration identity and no VS Code editor headers. Request settings cannot override the account or integration identity. Custom and Enterprise gateways are not supported by this integration.

A model administrator can configure an approved profile with a Copilot bearer token in the vault. Do not use a general GitHub API token as evidence of Copilot access. Select personal model credentials on a shared agent to let each member connect their own account through chat settings. A deployment administrator must first set `GITHUB_COPILOT_OAUTH_CLIENT_ID` to AgenticOS's own GitHub OAuth App client ID with device flow enabled. The member opens GitHub's authorization page, approves the code shown in AgenticOS and checks authorization. No device code or token appears in a URL. Reconnect repeats this flow; disconnect removes the private stored token, while OAuth revocation is done separately in GitHub settings.

GitHub authorization alone is insufficient: before saving the personal token, AgenticOS verifies that this account and application advertise the selected model on `/chat/completions`. Catalogs are account-specific, filtered by supported endpoints, and have no global fallback. Copilot's Responses, Messages, embeddings and realtime interfaces are not offered. Personal connections retain the existing signed-in web-chat restriction and cannot fall back to an organization key or another provider.

The device flow accepts non-expiring OAuth App grants. Expiring or refreshable GitHub App grants are explicitly refused; their renewal is not implemented, and refresh tokens are never silently discarded. Missing entitlement, policy, revocation and quota failures require reconnect or account action. Model names alone do not establish a subscription bill: Copilot plan usage is unpriced until a USD billing contract is verified; quota fields are not interpreted as dollars. Real-account acceptance for AgenticOS's own OAuth application and integration identity remains pending. See [Pydantic AI Copilot](https://pydantic.dev/docs/ai/models/github-copilot/) and [GitHub OAuth setup](https://docs.github.com/en/copilot/how-tos/copilot-sdk/setup/github-oauth).

## Official ChatGPT plan usage

**ChatGPT plan usage (official)** uses an application-specific grant and the public Responses API. **ChatGPT (Codex subscription)** remains the separate Codex backend integration. Their sign-ins, vault kinds and tokens are not interchangeable.

Official plan usage is disabled by default. An operator must verify deployment eligibility, set `OPENAI_CHATGPT_PLAN_USAGE_ENABLED=true` and persist one UUID in `OPENAI_CHATGPT_HOST_ID` across restarts and replicas. Paid or remotely hosted applications require OpenAI's approval. These settings attest eligibility; they do not obtain approval. Restore the original host UUID before reconnecting an existing installation.

Choose the official provider in the Vault or model picker, sign in and paste the final `http://127.0.0.1:1455/auth/callback?...` address. The grant is stored privately. Only its owner can spend it; shared profiles, API keys and background work cannot lend it to another person. Declining plan sharing saves the registration and grant, displays a warning and cannot enable inference. Reconnect to request consent again. Issued client registrations survive failed token exchanges; callbacks are single-use and bound to the initiating member and organization. Another sign-in supersedes earlier callbacks.

Select a model from the selected grant's live account catalog. Listings are not replaced with a global API-key catalog. Rotating tokens return to the vault with compare-and-swap checks, and every model request checks grant revocation and the owner's current membership. Delete the vault grant to disconnect locally; revoke application access in ChatGPT settings to revoke it at OpenAI. Registration metadata remains for a later reconnect.

Pydantic AI enforces streaming, `store=false`, local history replay and the supported preview dialect. Suspended-response retrieval, Batch API and unsupported hosted tools are unavailable. Official plan usage cannot participate in automatic model fallbacks. Usage remains unpriced in AgenticOS; an API price estimate would not establish the plan's charge. Account entitlement, live quota and billing acceptance require testing with an eligible account. See [OpenAI's flow](https://developers.openai.com/siwc/token-sharing-open-source) and [Pydantic AI's adapter](https://pydantic.dev/docs/ai/models/openai-chatgpt/).
