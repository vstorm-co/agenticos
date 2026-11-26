# Native subscription credential storage

Maintainer decision, 2026-11-23, for PR #3137: retain CLIProxyAPI's native
credential storage for this release, as an explicit exception to the Vault rule.
This is not a general exception for application credentials.

## Why the native store remains

AgenticOS embeds the CLIProxyAPI binary and runs an isolated process for each
organization, person and membership generation. The binary owns provider sign-in,
token refresh and account management. Its auth directory is its authoritative
store; AgenticOS currently has no Vault adapter for it. There is no evidence
that a complete Vault adapter was implemented and rejected as unworkable.

Credentials change while a process runs. A refresh must durably retain its new
tokens even when later agent work fails. Codex also maintains refresh claims and
receipts in a durable journal, to recover without reusing a consumed refresh
token. Some management and Codex persistence paths access files directly rather
than exclusively through the token-store interface.

A startup/shutdown synchronization would lose this state on a crash. Switching
to upstream's Postgres store does not provide AgenticOS envelope encryption and
still uses local files. A full Vault integration therefore needs a reviewed
adapter or upstream change covering every persistent mutation and the journal,
not an encryption wrapper around process shutdown.

## Current protection and limits

The `subscription_accounts` volume contains provider tokens/account state, refresh
journals, per-process `keys.json` and `config.yaml`. Directories use `0700`,
configuration/key files `0600`, processes bind to loopback, and the gateway has no
publicly published port. Scope is derived by the backend from the organization,
person and membership generation; disconnect and departure schedule cleanup.
Other model-account integrations continue storing credentials in Vault.

These file permissions and routing controls do not encrypt copied files or
backups, do not cryptographically bind their contents to the owner, and do not
participate in Vault master-key rotation. Operators must protect this volume and
its backups, including encryption at rest where required by their policy. The
application does not establish that protection itself. Treat the entire directory
as credential material; do not log, export or commit it.

## What a future Vault implementation must prove

Persist tokens, account metadata and refresh-journal claims/receipts on every
change, with atomicity/CAS and defined handling of unknown write acceptance.
Preserve concurrent refresh and restart recovery, owner and membership scoping,
revocation and deletion, Vault rotation and migration of existing native files.
Exercise process crashes and concurrent refreshes in regression tests. Required
working files may be temporary, but cannot be the sole authoritative copy. Keep
owner resolution in the backend rather than giving the gateway the master key.
