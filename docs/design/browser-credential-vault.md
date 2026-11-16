# Browser credential Vault

**Status: proposal only.** This design does not add secret kinds, expose
credentials, modify browser permissions or deploy autofill. The schemas and
endpoints below are proposed contracts for separate implementation PRs.

Baseline: T3OS `080c12941ed06cce2e92b6b03910e94ace36469e`, inspected on
14 November 2026. Benchmark:
[OpenBot v0.71.0](https://github.com/nightly-labs/openbot/releases/tag/v0.71.0),
including its [documented browser Vault additions](https://openbot.run/changelog).
This is an independent design for T3OS's existing architecture.

## Problem and scope

T3OS already encrypts technical credentials, controls access to each secret and
keeps browser sign-ins. What is missing is a browser-oriented credential flow:
save a login for specific sites, select it without exposing its password to the
model, fill an observed login form and supply a time-based one-time password
(TOTP) when the site asks for one.

Extend the existing Vault with a browser login and an optional contact/address
profile. Use the provisioned server browser as the default and only execution
surface for this release. Do not attach a personal browser or read the user's
password manager, clipboard, browsing history or computer.

Keep API keys and OAuth connections on their existing paths. A saved browser
login is not an API credential, and an existing cookie session is not converted
into a password. Payment card storage and payment submission remain separate
future work; this proposal does not claim that part of OpenBot parity.

## Existing implementation to reuse

| Verified module | Decision |
|---|---|
| `backend/app/core/vault.py` | Use the existing owner-bound envelope encryption and key rotation. No new encryption mechanism or master key. |
| `backend/app/core/secret_kinds.py` | Add typed browser payloads and their JSON schemas here. Existing kinds remain unchanged. |
| `backend/app/db/models/organization_secret.py` | Reuse secret identity, visibility, usage scope and `authorization_generation`. Changes to allowed use rotate the generation. |
| `backend/app/services/organization_secret.py` | Add a narrow browser writer that resolves authority and delivers values directly to the owned browser. Never return plaintext to an API caller or model. |
| `backend/app/api/routes/v1/secrets.py` | Reuse creation, replacement, metadata listing and resource access. Do not introduce a reveal endpoint. |
| `backend/app/services/browser_sign_in.py` | Preserve member-sealed cookie/local-storage sessions and their private audience restrictions. Cookie persistence remains a separate explicit choice. |
| `backend/app/agents/capabilities/browser_use/_direct.py`, `_page.py`, `_preview.py` | Reuse observed element handles, allowed domains, live browser ownership and human-control lease. |
| `frontend/src/components/vault/secret-form.tsx`, `secret-dialog.tsx` | Extend schema-driven forms with browser-specific input and masked metadata. |
| `frontend/src/components/chat/browser-panel.tsx`, `browser-view.tsx` | Add the credential picker and destination confirmation inside the hosted browser panel. |
| `frontend/src/components/browser/my-sign-ins.tsx` | Keep saved sessions separate from saved passwords and explain their relationship. |

Read [Secrets and the vault](../secrets.md) and
[Permissions](../permissions.md) for the current contracts. The implementation
must preserve their guarantees rather than introducing a parallel store.

[PR #89](https://github.com/t3grp/agenticos/pull/89) is the hosted-panel UX
dependency. Integrate with its accepted implementation or an equivalent reviewed
launcher. This design neither changes its release state nor republishes agents.

## Product flow

1. In Vault, choose **Browser login**. Enter a label, username, password and one
   or more exact allowed origins. Add a TOTP seed only when the owner deliberately
   chooses to store it.
2. Save as a personal credential by default. The UI explains that use is limited
   to the owner acting privately, and shows which agent bindings allow it.
3. In the hosted browser, choose **Use a saved login**. The server lists only
   eligible metadata for this member, organization, agent, run and destination.
4. Show the exact destination origin and which fields will be filled. The first
   implementation requires a human confirmation for each fill operation.
5. The server fills the observed fields directly. It returns only success or a
   bounded refusal reason. Filling does not submit the form.
6. The user or agent submits through the existing browser action path and its
   approvals. A later TOTP challenge is a separate fill operation with a fresh
   destination and authority check.
7. After a successful sign-in, the existing **Keep me signed in** choice may save
   a cookie session. Removing the password does not silently remove an existing
   cookie session; the UI offers an explicit link to forget those sessions.

A contact profile follows the same destination-confirmed fill path and exposes
only the selected fields. It does not turn a form submission or purchase into
an implicitly authorized action.

## Proposed secret kinds

Use discriminated, extra-forbidden Pydantic models in `secret_kinds.py`.
Secret-bearing fields use `SecretStr` and secret-safe serialization. Validate
the entire payload before sealing; listing and error responses are separate
metadata schemas.

| Kind | Sealed fields | Metadata allowed in listings |
|---|---|---|
| `browser_login` | Username, password, exact allowed origins, optional TOTP seed/algorithm/digits/period, optional reviewed field-role hints | Label, kind, allowed origins, owner/scope, last-used time, `has_totp`; no password or seed hint |
| `browser_profile` | Reviewed name, email, phone and structured address fields; exact allowed origins | Label, kind, allowed origins and available field names; no profile values |

Proposed login shape, showing synthetic placeholders rather than a usable secret:

```json
{
  "kind": "browser_login",
  "username": "<submitted through the secret form>",
  "password": "<submitted through the secret form>",
  "allowed_origins": ["https://portal.example.test"],
  "totp": {
    "seed": "<base32 seed submitted through the secret form>",
    "algorithm": "SHA1",
    "digits": 6,
    "period_seconds": 30
  }
}
```

Accept only HTTPS origins without paths, query strings, fragments, userinfo or
wildcards. Canonicalize hostnames and ports once and compare canonical origins
at use time. Deny browser-internal, local and private-network destinations in
the initial release; a future enterprise intranet policy needs explicit review.

The TOTP parser accepts validated Base32 seeds and explicitly supported
algorithms, digits and periods. Do not add an opaque `otpauth://` URL field
whose query could appear in validation errors. If import is added, parse in the
secret form and submit the typed payload; never log the import URI.

New browser kinds use empty hints. A short valid password must not be rejected
merely to support a last-four-character hint, and that hint must not disclose it.
A missing password may not mean 'preserve the old value' in a replacement request:
use an explicit replacement contract so clients cannot accidentally clear fields.

## Ownership and authorization

The first rollout supports personal use only:
`usage_scope=personal`, `visibility=private` and a non-null owner. Require the
run to act as that owner in a private, admitted human audience. No anonymous
embed, public shared conversation, outsider channel, impersonated run or
publisher-fallback context may borrow the credential.

The current `OrganizationSecretService` seals even personal-use technical keys
with `VaultScope.organization(...)`. Personal use is an authorization restriction
there, not member-bound encryption. Browser passwords need the stronger boundary
already used for personal browser sessions, extended to include the organization.

Add a proposed `VaultScope.browser_member(organization_id, user_id)` through the
existing envelope mechanism, with a distinct scope kind and a stable subject
derived from both ids. One browser-kind scope resolver must serve creation,
replacement, browser use and `vault-rotate`; generic technical-key readers must
refuse the new kinds. Existing secrets keep their current scope. Integration
tests must prove that changing either id prevents unsealing. No additional master
key or encryption implementation is introduced.

The first release refuses changing a browser record's owner or personal usage
scope. Shared-account support must perform an explicit authorized rewrap under
its chosen organizational scope; editing metadata alone cannot transfer a login.

Per-resource operations use `resolve_access`, including grants. Collection
creation follows the existing `secrets:edit` gate. Metadata visibility alone
does not authorize browser use. The current runtime's personal-use restrictions,
the frozen published agent binding and the explicit browser-use policy must all
permit the operation.

The first implementation adds a proposed `browser_credential_ids` list to the
`browser_use` binding. Validate ids and allowed use at publication. Recheck
membership, secret existence, usage scope, grants, agent identity and
`authorization_generation` immediately before each fill. A previously approved
plan does not survive a password rotation or access change.

Organization-shared logins are a later slice. They require explicit opt-in,
named agent grants and a clear 'act as this shared account' policy. Never infer
that an organization-wide label or a builder's ability to view a secret permits
every agent or member to use it.

## Narrow browser-use contract

A credential fill is a server operation attached to an existing run and browser
session. It does not accept a CDP URL, JavaScript, CSS selector or arbitrary
destination URL. The request refers only to an observed tab, current page
generation and fresh element handles.

Proposed internal command:

```json
{
  "run_id": "<existing authorized run>",
  "browser_session_id": "<owned hosted session>",
  "tab_id": "<observed tab>",
  "page_generation": 12,
  "secret_id": "<eligible vault reference>",
  "authorization_generation": "<current generation>",
  "operation": "login",
  "field_handles": {
    "username": 21,
    "password": 22
  },
  "confirmation_id": "<single-use human confirmation>"
}
```

The server derives origin and agent identity from the live page and run. It
checks the top-level origin, frame origin, form destination where observable,
field roles, visibility and page generation. Cross-origin frames, hidden
controls, unknown form destinations and navigations during validation are
refused in the first release.

The writer holds the browser's input lease and observes the page again
immediately before sending values. If navigation changes the origin or page
generation, invalidate the confirmation. A redirect must be inspected at its new
origin; allowlisting the starting site does not authorize a different one.

Password and TOTP fields must match the expected observed form roles. The
operator resolves an ambiguous form by taking control. Do not broaden the
origin list or infer credential permission from instructions on the page.

## Proposed API and capability surface

| Proposed surface | Contract |
|---|---|
| Existing secret creation/replacement routes | Accept the two new typed kinds after validation and seal them through the existing service. Return metadata only. |
| `GET /v1/runs/{run_id}/browser-credentials` | Eligible metadata for the current owned hosted browser, scoped to its observed origin. Inaccessible ids are not enumerated. |
| `POST /v1/runs/{run_id}/browser-credential-plans` | Validate observed handles and issue an expiring, single-use plan for the human to review. Store ids and field roles, never values. |
| `POST /v1/runs/{run_id}/browser-credential-plans/{id}/confirm` | Confirm as the current human owner, recheck authority and origin, and fill once. A duplicate never blindly retries. |
| Proposed `browser_fill_credential` tool | Request a plan by secret reference and observed handles; return the required human confirmation or a refusal, never credential values. |

Extend the existing `browser_use` capability and its declared `tools=` tuple.
The new tool is explicitly side-effecting and must use the existing approval
system. Per-resource routes delegate authorization to the service; broad role
checks cannot override a resource grant.

Plans expire after 60 seconds and after any page-generation, lease or
authorization-generation change. TOTP codes are generated at fill time, never
when a plan is created, and are not retained. If the remaining code lifetime is
too short, wait for the next valid window within a bounded timeout or ask the
person to retry.

Record acceptance before the external browser effect using the run's existing
durable operation pattern. If a timeout leaves the fill outcome unknown, show
that state and require fresh observation. Do not automatically send another
password or code and do not automatically submit a form.

## Plaintext and browser output boundary

Plaintext travels only from the vault reader to the narrow browser writer in
memory. It must not enter model arguments, tool results, chat messages, logs,
trace spans, audit payloads, exported specs, workflows, teaching recordings,
screenshots retained as artifacts or error details.

Before filling, suppress capture of the target fields and clear cached DOM
snapshots for that page generation. Redact their values from subsequent DOM
reports and mask them in preview frames while present. TOTP input is treated as
sensitive even if the page renders it as ordinary text. Pause any browser teaching
capture across the operation.

The destination website necessarily receives the submitted credential. Origin
allowlisting is therefore a security boundary, not just a picker filter.
Page scripts at that allowed origin can observe form input. Do not claim that
autofill protects against a compromised allowed website or that masking inputs
is comprehensive page-content data-loss prevention.

A website that echoes a secret outside its input fields is a remaining output
risk. Release acceptance must include this adversarial fixture. Sensitive values
must be removed from retained DOM/text results, and preview must remain
suspended if the output cannot be safely masked. Do not resume captures merely
because a submit button was pressed.

The audit entry records actor, organization, agent, run, secret id, canonical
origin, operation, result code and generation. It contains no username, code,
password, profile value or raw page response.

## Implementation slices and acceptance

| Slice | Deliverable | Required evidence |
|---|---|---|
| 1. Types and storage | Browser kinds, schema forms, personal defaults and masked metadata | Cross-owner and cross-tenant unwrap refusal; invalid payload errors contain no values; key rotation preserves valid envelopes. |
| 2. Eligible selection | Published binding validation and origin-scoped metadata picker | Another user, agent, organization or revoked generation cannot discover or spend the credential. |
| 3. Login fill | Human-confirmed plan and direct server writer, without form submission | Correct field fill on a synthetic site; stale handles, hidden fields, redirected origins, takeover loss and ambiguous outcomes refuse safely. |
| 4. TOTP and profile | Just-in-time code and field-selective profile filling | Clock-boundary tests, supported algorithms, expired confirmations, unselected profile fields and no code retention. |
| 5. Shared-account policy | Explicit organizational opt-in with named agents | Positive authorized case plus grant revocation, member removal, shared-room and publisher-fallback refusal. |

Extend `backend/tests/api/test_no_secret_escapes.py` and the focused vault,
browser and permission suites. Add synthetic browser tests whose test-only
server receives the values while transcripts, audit entries, traces, screenshots
and the teaching store do not. Test prompt injection requesting a code through a
normal text tool, a malicious cross-origin iframe and a page that echoes the
password. No real credentials or client accounts belong in test fixtures.

Verify schema-driven forms, accessible field labels, error messages, account and
organization switching, and the difference between saved passwords and saved
sessions. Existing sign-in-session tests must remain green.

## Rollout, migration and rollback

No existing credential is converted automatically. Do not reserve an Alembic
number in this proposal. The implementation checks whether adding typed payloads
needs a migration, and any new plan tables receive numbers against the current
single-headed migration chain.

Ship behind a deployment flag, disabled by default. Enable personal login fill
for a synthetic test organization first, then selected users. TOTP, profiles and
shared accounts each have separate rollout gates. Add published documentation,
Vault/browser onboarding, translations and permission-aware UI in their
implementation PRs.

Disabling the feature blocks new plans and invalidates pending plans immediately.
Existing sealed browser records remain manageable and rotatable, and may be
deleted through the normal authorized Vault path. Never downgrade to a build
that cannot safely parse their metadata without an explicit compatibility plan.
Do not erase existing saved cookie sessions or rotate unrelated credentials
during rollback.
