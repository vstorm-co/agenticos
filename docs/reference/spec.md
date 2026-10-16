# The agent spec

The most load-bearing type in the platform: the Builder edits it, the database
versions it, the factory instantiates it, and clients export it to their own git
repositories as YAML.

Generated from the source, because the reasoning lives in the docstrings.

::: app.agents.spec.AgentSpec

## Delegation

Two shapes, and [Concepts](../concepts.md#delegate-vs-inline-specialist) explains
which to reach for. `subagents` holds the first; the second lives in the
[`subagents` capability's](capabilities.md#delegation) own config.

::: app.agents.spec.SubagentRef

::: app.agents.spec.SpecialistSpec

## Budgets

::: app.agents.spec.BudgetSpec

## Alerts

::: app.agents.spec.NotificationSpec

::: app.agents.spec.AlertSpec

::: app.agents.spec.AlertAudience

## Model settings

::: app.agents.spec.ModelSettingsSpec

## Observability

::: app.agents.spec.ObservabilitySpec

## Speech to text

The provider, model, key and language an agent's dictation and inherited channel
voice notes are transcribed with, where they differ from the organization's. The
key is a vault secret id, never the key itself.
[ML services](../ml-services.md#which-engine-a-recording-reaches) has the order
they resolve in. A spec that carries this block cannot be imported into a
deployment older than the block: its spec refuses fields it does not know.

::: app.agents.spec.SpeechToTextSpec

## Voice

How the agent holds a [voice call](../voice.md): the realtime model, the vault
key, the voice and the call's own limits. Optional, and an all-empty block reads
as no block, so specs written before it load unchanged and `SPEC_VERSION` did not
move. Like the speech-to-text block, a spec that carries it cannot be imported
into a deployment older than the block.

| Field | What it holds |
|---|---|
| `provider` | A provider from the realtime catalog: `openai`, `azure`, `google` or `xai` |
| `model` | A realtime model of that provider. For Azure, leave it empty and use the two fields below |
| `deployment` | Azure only: the deployment name calls go to |
| `base_model` | Azure only: the catalog model that deployment runs, which decides its voices and its price |
| `secret_id` | The vault key calls are held with - an id, never the key |
| `voice` | One of the model's voices; empty uses the model's default |
| `language` | An ISO-639-1 code the agent speaks; empty follows the caller |
| `max_call_seconds` | The longest call, 60 to 3000, and at most the organization's longest call |
| `voice_note` | Up to 1000 characters added to the agent's instructions in calls only |

Every rule that spans fields is checked when the version is published, not while
the draft is saved, because the Builder autosaves between picking a provider and
picking its model. Publishing is refused, naming the voice section, when:

- a provider is missing, or this deployment's catalog has no such provider;
- the model is missing or is not a realtime model the catalog offers for that
  provider (for Azure, the base model), or an Azure section names no deployment;
- the voice is not one of the model's voices;
- no key is chosen, or the key fails the shared check: its purpose is not the
  provider, its kind is not the provider's (`api_key`, or `azure_openai` for
  Azure), it belongs to another organization, or the publisher cannot see it;
- the language is not a code calls accept;
- the longest call is above the organization's longest call.

Capabilities a call cannot run do not block publishing; they are left out of
calls and the Builder lists them.

::: app.agents.spec.VoiceSpec
