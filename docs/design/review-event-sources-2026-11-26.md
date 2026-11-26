# Reusable event sources release review

Reviewed PR #3105 at `d8f7f1a2801ec86fe43d7bcba30e8ab7bccee5d7`, based on
`bb09fedf19b10f897c6a55dbdcd76a212dc9a275`, and integrated its selected diff onto
`0c9e016732e5bb7da4fabdb612526c88aac5e656`. That base is a shared ancestor; no
unapproved feature parents were imported. The existing review threads were checked
against this head, including receipt-time consent, retries, auth-before-lock,
credential/header exclusion, sample atomicity, literal prompts and pending reveal.
The historical automated-review failure is not treated as a clean review.

## What it adds

Reusable Event sources have a private-by-default management page, provider presets,
Vault-sealed credentials, resource grants and one authenticated JSON endpoint. Each
accepted receipt and its subscriber dispatch jobs commit together. Routines retain
literal prompts and receipt-time source consent. Workflows retain their pinned
version/principal and existing body/delivery_id output. Temporary capacity failures
stay pending for delayed retry; independent subscribers do not share execution.

Editors can inspect an authenticated live delivery without interrupting dispatch,
or paste workflow test JSON without executing a target. Live capture requires source
Use permission; editing a target alone does not grant capture. Subscribers keep their
own target authority and budgets. Dedicated existing URLs remain valid; synchronous
Respond to webhook uses an explicitly selected dedicated endpoint.

## Integration corrections

- Added `eventSources` to the console presentation vocabulary. Without this,
  the new navigation registry entry was absent from role/user policy controls
  and could be hidden by the inherited allowlist. Existing parity tests cover it.
- Named the credential form's fieldset with an existing translated legend, keeping
  the disabled-while-pending group accessible without changing visible layout.
- Limited the receipt/capture regression's Redis stall to its sample key. General
  middleware cache reads must not be stalled by a test of optional live capture.
  The test still proves commit-before-capture and HTTP completion while capture
  is blocked; commit failure starts no sample operation.
- Resolved aggregate CHANGELOG, model export, query-key and locale conflicts by
  preserving both approved scopes. Translation dictionaries were merged by key;
  no existing policy, cost or portability strings were replaced with old snapshots.

## Security and lifecycle assessment

Verified raw-byte signatures and constant-time byte comparisons, bounded input,
pre-auth ingress rate limiting, post-auth row locking with auth-envelope rechecks,
organization-bound Vault encryption/rotation and write-only credential responses.
Checked tenant-composite foreign keys, resource-grant checks, subscriber binding
permissions, captured-sample owner/source scope and independent workflow-run access.

Verified durable dispatch and duplicate receipt admission, restart behavior,
receipt-time routine policy identity, pinned workflow publisher/version, target
revocation, quota retry, paused-source receipt retention, and terminal payload
cleanup. No additional confirmed product security blocker remained in this scope.

## Validation and remaining train work

- Auth/management/receipt/sample unit batch: 150 passed.
- Real pgvector PostgreSQL source/routine batch: 45 passed, including concurrent
  deduplication, credential/configuration rotation races, tenant FKs, queue rollback,
  restart, grant loss, source rebind, capacity retry and payload retention.
- Corrected route/console-policy batch: 105 passed. Other workflow/Vault checks
  passed in the preceding scoped batch; the isolated test-fixture failure was
  corrected and rerun through the route batch.
- Frontend source/filter/new-routine batch: 39 passed; routine/workflow UI,
  navigation parity and dashboard widget batch: 62 passed, all on one worker.
- Hook/widget API batch: 156 frontend tests passed on one worker.
- Scoped ty, Ruff, translation and generated Architect-guide checks passed.
- Strict four-language MkDocs build passed; source controls keep their actual
  localized copy and the standard form/dialog components.

Migration `0365_reusable_event_sources.py` retains its published revision and
`0364_merge_routine_and_kb` parent. This intermediate worktree deliberately has
parallel heads; the release train must add its final merge revision before the
single-head guard, combined schema check and migration suite. Drain old workers
before new source job kinds can be queued, as the upgrade documentation explains.

The aggregate workflow portability boundary must omit source_id, report its omitted
path in the import review, and retain require_source=true in the private draft.
Reusable source UUIDs and credentials are not portable dependency copies. The root
integration applies this explicit reconnect contract after both feature commits;
the isolated source branch does not import the workflow-portability parent.

Final combined-sha CI, browser screenshots and deployment are separate evidence.
No paid model calls, external provider deliveries or production changes were made.
