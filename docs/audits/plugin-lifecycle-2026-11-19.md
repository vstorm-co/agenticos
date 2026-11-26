# Plugin lifecycle verification, 2026-11-19

The extension of PR #3180 was checked locally on macOS ARM64, Docker 29.2.1,
with the repository's pinned Python 3.15. No production deployment was modified.

## Published-image deployment

The disposable smoke driver used official release `1.84.0` images:

- Backend digest: `sha256:46a7744a2b092bfbadb3fd334775cf3623fa489b890161229543f6e49bbc050f`.
- Frontend image ID: `sha256:f3c1e4d70448305e5fe42eabab4990c71690bf1c9cbe7dc84e9bf5746f49d266`.
- PostgreSQL: `pgvector/pgvector:pg16`; Redis protocol: `valkey/valkey:8-alpine`.

Migrations completed. Bootstrap created the isolated organization and owner.
The console returned HTTP 200 and API readiness passed. A real MCP client
created and published an agent, ran it against a deterministic local
OpenAI-compatible fixture and reread the persisted completed run.

Run ID: `fef7e7b2-8974-4294-979c-22722d9fdad1`. Its answer was
`AgenticOS smoke check passed.` The disposable Compose project was
`agenticos-smoke-e95bfe3e`; its containers, networks and volumes were removed.

This verifies baseline platform plumbing on published images. New contract-1
operations were tested from source through the MCP/ASGI boundary and a real
database, not claimed to be present in the published 1.84.0 image. Paid model
providers, production TLS, external DNS and a remote host were not tested.

## Lifecycle and bundles

Real-database tests covered OAuth dataset creation, case insertion, scope
refusals, tenant isolation, secret reference metadata without hints, immutable
version reads, staging, promotion and rollback. Bundle tests covered private
bindings, the three shipped workflow/table templates, explicit embedding
references, atomic rollback on failure and concurrent same-key replay.

The new lifecycle module, solution service and receipt repository reached 100%
statement and branch coverage in their scoped tests. The migration was applied,
downgraded and reapplied in a disposable schema based on the previous model
state; `make db-check` then reported no upgrade operations. The complete
migration chain and full platform coverage suite remain CI checks.

The local Docker credential helper initially blocked anonymous pulls; an isolated
Docker configuration without credentials reached the public images. The normal
configuration was preserved. Smoke iterations also verified cleanup after failed
configuration and HTTP redirect handling before the successful run.
