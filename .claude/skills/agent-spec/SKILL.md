---
name: agent-spec
description: Change the agent spec — add or remove a field, rename one, tighten a rule, bump SPEC_VERSION, change publish-time validation, or touch YAML export/import. Use whenever editing app/agents/spec.py or anything that reads a stored spec. Every published agent and every client git repository holds a copy of this format, so a change that only works forwards breaks agents nobody touched.
---

# The agent spec — the format you cannot break

`app/agents/spec.py`. Reference page: `docs/reference/spec.md` (generated from the
docstrings, so the reasoning belongs in the docstring). Concepts:
`docs/concepts.md`.

The most load-bearing type in the platform: the Builder edits it, the database
versions it, the factory instantiates it, and clients export it as YAML into their
own git repositories.

## The constraint

**Old specs must keep loading.** A published agent's spec is stored as it was
written. A change that only parses new documents is a 500 on every run of something
nobody touched.

`model_config = ConfigDict(extra="forbid")` means an unknown key is a hard error, so
this is not theoretical. `SPEC_VERSION` is currently **11**.

## What each change costs

| Change | Cost |
|---|---|
| **Add** an optional field with a default | Free. Old specs take the default |
| **Add** a required field | Not allowed. Give it a default, or a `mode="before"` validator that supplies one |
| **Rename** a field | A `mode="before"` validator that moves the old key. `CapabilityBindingSpec._fold_the_knowledge_capabilitys_own_rename` is the worked example |
| **Remove** a field | Drop it in a `mode="before"` validator and **log a warning** — never let `extra="forbid"` raise on a stored spec. See `_MODEL_SETTINGS_WITHDRAWN` |
| **Narrow** a rule (shorter max, tighter pattern, new enum) | The dangerous one — see below |
| **Move** behaviour to a capability | Fold the old value into a binding, don't just drop it. `_with_thinking_binding` is the pattern |

Bump `SPEC_VERSION` whenever a stored document needs migrating, and write the
migration in the same change.

## Narrowing a rule is a data migration

A narrower rule does not only reject new input — it makes **existing rows
unreadable**, and a Pydantic model that refuses to validate one field of one row
takes down the whole listing endpoint with a 500.

`IngestionConfig` and its OCR language codes are the worked example outside the
spec: `ocr_language` went from "anything 2–16 characters" to Tesseract's
`^[a-z]{3}(\+[a-z]{3})*$`, and every row written before it held `"en"`. The data
migration shipped in the same revision.

If you narrow anything in a spec field, the same applies: find every stored value
first, and migrate it in the same change.

## Two invariants a migration must preserve

**Idempotence.** An explicitly-set value wins over a migrated one, so re-reading a
spec the validator already migrated changes nothing. Both existing validators are
written this way; keep it.

**Refusal at publish, never at run time.** An unknown capability id, an ungranted
scope, a `tool_approval` keyed on a tool that does not exist, an unrenderable tool
name, a `secret_id` of the wrong kind or from another organization, a **personal** MCP
connection — all refused while somebody is looking at a form. Validation added to the
runner instead is a broken agent in production rather than a red field in the Builder.

`app/services/agent_registry.py` owns publish validation. `_tool_override_problems` is
the shape to copy: collect every problem and report them together.

## What the spec deliberately excludes

Anything about *where* it runs (surfaces, channels, exposures) and *who* may use it
(owner, sharing). Those are deployment and access facts; keeping them out is what lets
the same spec be exported, reviewed and reused across organizations.

It also carries **no secret values** — only `secret_id` references. A spec goes into a
client's git repository.

## YAML

`to_yaml` keeps spec order rather than sorting, so a diff reflects what changed rather
than where it happens to sort, and UUIDs become strings so the file round-trips
through any reader. `from_yaml` raises `ValueError` on a non-mapping document, because
a list or a bare string reaches Pydantic as an unhelpful type error.

Round-trip is part of the contract: `spec == AgentSpec.from_yaml(spec.to_yaml())`.

## Test

`tests/test_agent_spec_and_factory.py`. Every migration needs a test that loads a
**verbatim old document** — not one built from the current model, which cannot fail.
Plus the round-trip, the duplicate-capability refusal, and each publish refusal.

`app/agents/**` is held to 100%. See the `backend-tests` skill.
