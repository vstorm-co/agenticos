---
name: vault-secrets
description: Store, read or rotate a credential — a provider API key, a channel bot token, an MCP token, a third-party service key — or add a new secret kind. Use whenever a change touches a credential at rest, whenever something needs to be encrypted, and whenever reviewing code that could leak a plaintext key into a response, a log line or an audit entry. Everything seals through app/core/vault.py; there is deliberately no second mechanism.
---

# The vault — one mechanism, bound to an owner

**Read `docs/secrets.md`.** The module docstrings in `app/core/vault.py` and
`app/core/secret_kinds.py` carry the reasoning.

## The rule

Every provider key, channel bot token, MCP credential and third-party API key seals
through `app/core/vault.py`. **There is no second mechanism, and adding one is the
mistake this design exists to prevent.**

`CHANNEL_ENCRYPTION_KEY` and the deployment-wide Fernet keys are **gone**, removed
before the migration chain was squashed into `0001_baseline`. If you see them
referenced anywhere — code, docs, a skill, an `.env` example
— that reference is stale. Three mechanisms used to hold secrets and only one bound a
ciphertext to its owner; a Slack token could be copied from one organization's row
into another's and it decrypted.

## Envelope, and what it buys

Each secret is sealed with its own random data key. That data key is sealed with a key
derived from the master key **and the scope that owns the secret**.

- **A ciphertext cannot move between owners.** A row copied from org A into org B
  fails to unwrap. Tenant isolation here is cryptographic, not a `WHERE` clause
  somebody might forget.
- **The master key is rotatable.** It never encrypts payloads, only data keys, so
  rotation re-wraps one small blob per secret. `key_version` records which master key
  sealed an envelope — that column is what makes a staged rotation possible.

Scope is an **organization**, or the **member** for a personal MCP connection (which
has no organization, and whose owner may belong to several).

`VAULT_MASTER_KEY`, falling back to `SECRET_KEY` so a fresh checkout runs. An
environment validator refuses the default `SECRET_KEY` outside development.

## Kinds

A secret is not always a string, and the kind decides which fields exist:
`none`, `api_key`, `azure_openai`, `aws_credentials`, `gcp_service_account`.

`StorableSecret` is what a person can save; `SecretValue` adds `none`, which the
runtime can hold but nobody can store. That difference keeps "a secret with no value"
out of the API schema. The vault refuses to seal an empty value.

Adding a kind means: a new model in `secret_kinds.py`, a branch in
`model_resolver._build_provider` if a provider needs it, a Builder form field, and a
migration only if a stored shape changes. Validate on the way in — the failure mode of
a malformed service account is an auth error hours later with nothing pointing back at
the paste that caused it.

## Four things that must stay true

1. **No API response returns a plaintext.** There is no endpoint for it.
   `OrganizationSecretService.resolve_for_bindings` is the *only* reader that yields
   plaintext, and the runner is its only caller. Do not add a second.
2. **No log line or audit entry contains one.** Every secret-bearing field is a
   `SecretStr`, which is what makes the carrying dataclasses mask themselves in a
   repr — the usual way a key escapes.
3. **No spec carries one.** A binding stores `secret_id`; specs are exported to
   clients' git repositories.
4. **A capability never learns where its credential came from**, and the model never
   sees it.

`tests/api/test_no_secret_escapes.py` pins these. If it fails, the leak is real.

## Declaring a need, not an instance

A capability declares a `SecretRequirement` — a *kind*. Code says "I need an API key";
a binding's `secret_id` says which one. `needs_secret(config)` is consulted by publish
validation and by the build, so the two cannot disagree.

A secret deleted *after* publish makes the run **refuse**, not degrade: a capability
whose whole job is calling an authenticated API does not do half of it, and a run that
quietly dropped the call would answer as if the API had said no.

## Access

`secrets:view` / `secrets:edit` (resource permissions, so they carry a scope),
`mcp:manage`, `connections:manage`. A secret can be shared to one member or agent with
a grant. See the `permissions-rbac` skill.

## Test

Cross-tenant unwrap must fail. That is an **integration** test — a mock cannot tell
you the binding holds.
