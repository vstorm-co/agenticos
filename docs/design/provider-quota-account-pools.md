# Provider quota visibility and account pools

**Status: proposal only.** No provider telemetry, new login, account selection,
migration or automatic retry is implemented by this document.

Baseline: T3OS `080c12941ed06cce2e92b6b03910e94ace36469e`, inspected on
14 November 2026. Benchmark:
[OpenBot v0.71.0](https://github.com/nightly-labs/openbot/releases/tag/v0.71.0)
and its [account/usage release notes](https://openbot.run/changelog).
This proposal is an independent implementation plan.

## Outcome and current boundaries

Show each authorized account's reported capacity, limits and reset time, with
its source and observation age. Let the owner explicitly select a named account
or an approved pool. Route a new request to an eligible account without silently
borrowing another person's subscription or replaying work whose outcome is
unknown.

T3OS already has model-profile fallback. Account selection is a separate step:
it chooses credentials for the requested provider/model within the caller's
authority. It does not turn every failed tool or model request into an invitation
to try another identity.

| Verified existing source | What it already provides |
|---|---|
| `backend/app/db/models/coding_account.py` | One coding account per organization, user and harness; enabled flag and authorization generation. |
| `backend/app/services/coding_accounts.py` and `personal_coding.py` | Personal account consent, isolated task execution and current-authority checks. |
| `backend/app/services/coding_account_lease.py` | A single renewable-credential lease; an occupied account returns an explicit busy result. |
| `backend/app/agents/model_resolver.py` | Configured model fallback using `FallbackModel`. Preserve this behavior independently. |
| `backend/app/schemas/claude_subscription.py` and `services/claude_subscription/_service.py` | Native Claude login state and owner-facing connection management, not quota telemetry. |
| `backend/app/agents/capabilities/coding_agent/_harness.py` and `harness/_sessions.py` | Existing harness adapters. Do not equate an installed harness with verified subscription login or limit reporting. |
| `frontend/src/components/settings/coding-accounts.tsx` and `personal-model-connections.tsx` | Current personal connection surfaces to extend. |

[Personal coding accounts](coding-accounts.md) defines current consent,
membership, isolation, lease and refresh behavior. Its single-account contract
remains true until an implementation migration and compatibility path land.

## Product behavior

The account list shows a label, provider, eligible models, connection state,
currently busy state and a bounded usage summary. A reset countdown appears only
when the provider actually supplies a reset timestamp. Unsupported or stale data
reads **Unknown** or **Last checked ...**, never zero usage or unlimited capacity.

Keep three concepts visibly separate: T3OS spending budgets, provider-reported
subscription limits and temporary provider capacity. They have different sources
and a budget remaining does not prove that a subscription can accept a request.

The first release adds read-only telemetry and explicit named-account selection.
A later release enables opt-in pooling. Its settings state account priority,
whether stale/unknown telemetry is eligible and the maximum number of alternate
admission attempts. Choosing a pool never changes account sharing or consent.

A run displays the selected account label and selection reason. A shared room
shows only metadata already visible to its audience; it must not expose a
person's private account label or quota. Personal subscription use stays limited
to the surfaces already authorized by the personal-account contract.

## Provider adapter contract

Add a provider adapter interface around existing authenticated runtime clients.
An adapter declares supported account identity, models, telemetry source,
refresh semantics and whether a rejected request is provably unaccepted.
Do not scrape account pages, import local CLI credentials or assume undocumented
usage endpoints exist.

Proposed normalized snapshot:

```json
{
  "account_id": "<opaque account reference>",
  "provider": "example_provider",
  "status": "available",
  "observed_at": "2026-11-14T15:00:00Z",
  "valid_until": "2026-11-14T15:05:00Z",
  "source": "provider_api",
  "windows": [
    {
      "name": "reported_window",
      "used": 40,
      "limit": 100,
      "unit": "provider_reported_units",
      "resets_at": "2026-11-14T16:00:00Z"
    }
  ],
  "reason_code": null
}
```

Each window records an explicit unit. A provider percentage cannot be converted
into tokens, requests or money without a documented mapping. Unknown fields are
null, not inferred from elapsed time. Allowed source values are
`provider_api`, `native_runtime` and `unavailable`; estimated values, if added
later, require a distinct visible source and never control automatic routing.

An account adapter must distinguish `available`, `busy`, `rate_limited`,
`quota_exhausted`, `capacity_unavailable`, `authentication_required`,
`disabled` and `unknown`. A transient network failure cannot label an account
as disconnected or clear its last valid observation.

Refresh runs through a bounded background job, deduplicated by account and
authorization generation. A manual Refresh request enqueues that job rather
than holding the web request open or launching multiple provider calls.

## Proposed account and pool model

Replace the unique organization/user/harness restriction only in a migration
that preserves existing ids. Add a stable provider account identity fingerprint
and an owner-selected label. Prevent the same provider identity from being
registered repeatedly in one owner's pool as if it supplied additional capacity.

A pool has organization, owner, provider, ordered account ids, explicit enabled
state, selection policy and revision. Start with personal pools only. An account
must belong to the same owner and organization, remain enabled, support the
requested model and have current consent. There is no cross-user or cross-tenant
pool selection.

Reuse `VaultScope.user` and the existing native runtime's credential custody.
A generic metadata record may reference either a sealed coding account or a
native runtime account handle. It must not copy native credentials into a
second store just to unify the picker.

Pool membership changes increment the pool revision. Credential or consent
changes increment account generation and invalidate cached telemetry, eligibility
decisions and leases held by stale work. Preserve single-use refresh token
serialization and compare-and-swap writes for every account.

## Selection and failure contract

Selection happens before a request or coding task starts. It uses an immutable
snapshot of requested provider/model, explicit account or pool, pool revision,
account generation and initiating authority.

1. Recheck current membership, run surface, owner consent and model eligibility.
2. Build candidates from the selected pool only. Exclude disabled, revoked,
   incompatible, known-exhausted and occupied accounts.
3. Order eligible accounts by the configured priority; a tie uses a stable id.
   The initial policy does not chase speculative percentages.
4. Acquire the existing per-account credential lease atomically. If another
   worker won it, reconsider the next candidate within the same bounded attempt.
5. Recheck authority and generations after acquiring the lease, then admit the
   request and record the chosen account.
6. Stop selection once the provider accepts work. A task keeps that identity for
   its lifetime; it does not move a live harness session between accounts.

A provider's explicitly unaccepted capacity/rate-limit response may permit one
alternate candidate when the owner enabled that policy. A timeout, dropped stream
or unknown acceptance does not. Reconcile the original request if the provider
offers a durable request id; otherwise surface the uncertainty.

Authentication failures request reconnect for that account. Policy refusals,
invalid input, tool approval denials and security restrictions do not trigger
account rotation. Model-profile fallback continues to obey its own configured
limits and must not multiply pool attempts into an unbounded retry tree.

No shared run may consume a personal pool merely because its requester belongs
to the organization. Preserve the existing restriction on schedules, anonymous
API keys, impersonation and publisher fallbacks. Organizational service-account
pools are a separately reviewed extension.

## Proposed API

| Proposed route | Behavior |
|---|---|
| `GET /v1/me/provider-accounts` | Caller-owned metadata and latest eligible snapshots in the active organization. |
| `POST /v1/me/provider-accounts/{id}/usage-refresh` | Enqueue one bounded refresh for the current generation; return job id and freshness state. |
| `GET/POST /v1/me/provider-account-pools` | List or create caller-owned pools. Creating a pool grants no account access. |
| `PATCH /v1/me/provider-account-pools/{id}` | Change ordered eligible ids/policy with an expected revision. |
| `POST /v1/me/provider-account-pools/{id}/preview` | Return eligible labels and reason codes for a requested model; do not lease or spend an account. |
| Existing run creation | Add an optional explicit account/pool reference through the existing model-choice contract; reject both being set. |

Use the current authenticated member and organization, never owner ids from a
request body. A caller who cannot access a connection receives the same response
as for a missing id. The run's server resolver rechecks every choice; picker
filtering is not authorization.

## Migration and compatibility

Existing account ids, tokens, enabled state and generation remain unchanged.
Each existing single account becomes the default named account for its current
harness. Do not create an enabled pool or alter consent automatically.

Old clients that omit account selection continue to use the existing default.
Once several accounts exist, the default must be explicit and unique. An
ambiguous default is a validation error, not an arbitrary first row.

Extend the native-runtime adapter only after its account identity and logout
semantics can keep two sessions separate. Gemini CLI, OpenCode or Pi support
does not itself authorize a new native provider login flow. New providers need
their own tested adapter and provider-supported authentication contract.

## Implementation slices and acceptance

| Slice | Result | Required evidence |
|---|---|---|
| 1. Telemetry contract | Read-only normalized usage snapshots with source/freshness | Fixture tests for missing windows, stale data, clock skew, rate limit, capacity and authentication; no secrets in API/error/log responses. |
| 2. Multiple named accounts | Backward-compatible records and explicit default | Migration preserves existing ids and consent; duplicate provider identity rejected; old clients retain their account. |
| 3. Manual account choice | Picker plus server admission | Forged ids, other-owner accounts, revoked generations and unsupported models refused; selected account persists across resume. |
| 4. Opt-in pool | Atomic lease and bounded pre-admission selection | Concurrent workers cannot spend one renewable credential twice; unknown acceptance cannot start a second task. |
| 5. Additional adapters | Each provider added independently | Real-provider acceptance receipt for sign-in, telemetry, refresh, disconnect and quota behavior; synthetic fixtures alone cannot claim these verified. |

Use deterministic adapter fixtures and targeted lease/concurrency tests first.
Live acceptance uses a deliberately chosen test account and a bounded task; it
does not exhaust subscriptions to manufacture quota signals. Extend the existing
personal-account tests, frontend picker tests and tenant refusal coverage.

## Rollout and rollback

Gate telemetry and pooling separately. Enable read-only snapshots first, then
named accounts and manual selection, then opted-in pools. Track admission
reason codes, lease contention, refresh failures and stale-data age without
account secrets, raw provider error text or private account addresses.

Disabling pools returns new requests to explicit/default account selection;
running work retains its admitted account and generation checks. Do not merge
multiple accounts back into the former unique row. A downgrade to the old schema
requires a reviewed migration plan and cannot silently discard credentials.
