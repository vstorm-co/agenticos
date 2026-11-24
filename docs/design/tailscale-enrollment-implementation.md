# Tailscale enrollment runtime

This implements the enrollment foundation proposed in [design PR #185](https://github.com/t3grp/agenticos/pull/185). Implementation was authorized on 20 November 2026. The feature is disabled by default.

## Scope and ownership

**Connections → More → Devices & networks** supports personal or organization records, explicit Tailscale sign-in, device approval, a last-observed peer snapshot, Refresh, Pause and Revoke. Creating or reading a record never starts a node. Successful enrollment retains encrypted identity after its short-lived runtime stops.

Target/service records, SSH, SFTP, remote browsing, HTTP forwarding, subnet routes, exit nodes, Funnel and general proxies are outside this slice. `networks:use` reserves a permission for following transport work; it exposes no tool now. Enrolled status proves tailnet membership, not service reachability or a policy grant. The peer snapshot is local node status, not an administration inventory or network scan.

Every connection belongs to one organization. Personal connections also belong to one member, and other members cannot read or administer them, including organization owners. The same person in another organization creates and enrolls a separate identity. Organization connections use existing resource scope/grant rules and a vault scope independent of whether their creator remains a member.

The catalog defines `networks:view`, `networks:manage`, and `networks:use`. Default scopes are ALL for owners, SHARED for admins/builders, and OWN for members. Operators have SHARED view/use and no management; viewers have none. The personal-owner restriction precedes generic grant resolution. The UI checks `networks:view` independently of `connections:view` and uses server-provided `can_manage` for each record.

Management and enrollment-link retrieval require the person's own active, non-impersonated session. API keys, workflows, routines, channel identities and publisher fallback contexts cannot borrow it. Workers recheck the initiating session, active membership and management permission while enrollment/status work runs.

## State and enrollment

Authentication, desired state, runtime and cleanup are separate fields:

| Situation | Desired state | Authentication | Runtime | Cleanup |
| --- | --- | --- | --- | --- |
| New record | paused | not connected | stopped | none |
| Connect queued | active | last observed state | starting | none |
| Sign-in available | active | sign-in required | running | none |
| Administrator approval required | active | approval required | running | none |
| Enrollment succeeded | active | authenticated | stopped after snapshot | none |
| Paused identity | paused | last observed state | stopping/stopped | none |
| Revocation committed | revoked | transitions to not connected | stopping/stopped | pending/manual/complete |

Only `GET .../{id}/enrollment` can return the login URL, to the initiating member in the initiating session during that attempt. The URL is separately encrypted in the vault. Public connection schemas, queue payloads and audit records omit it. The browser holds it in local dialog state, outside React Query and persistent storage, and polls every two seconds. Closing the dialog, scope switches, pause/revoke, expiry and terminal authentication clear it. Separate state polling can observe completion after the private link becomes unavailable.

Validation requires HTTPS, exactly `login.tailscale.com`, a path under `/a/`, no userinfo/fragment/control characters, and the default/443 port. Provider changes to this origin/path require reviewing both Python and Go validators. Successful private GET responses carry `Cache-Control: no-store`. Error envelopes contain no credential. Log redaction removes a login URL's entire bearer path and query; validation errors suppress input values.

Enrollment expires after ten minutes including queue delay. Explicit Refresh uses stored identity and a 45-second attempt deadline without offering a new sign-in link. Limits are one pending attempt per initiating person in an organization, four per organization, and ten non-revoked records per creator in an organization. Admission serializes before counting.

## Worker and broker

Durable jobs contain organization/connection/attempt IDs, policy generation and mode only. The separate `network` worker pool has two slots by default. Failed/expired enrollment is not automatically retried or restarted; the member reconnects explicitly. Recovery can retry revocation cleanup.

Each job owns one Go child process using `tailscale.com v1.104.7`, Go 1.27.4, `tsnet` userspace networking and a custom state store. Builds use Tailscale's `ts_omit_webclient` tag to exclude its unused web interface; the license collector receives the same tag and target architecture. There is no host TUN device, shared daemon, public application listener or proxy. The child runs as the worker OS account: this is process separation, not a separate container or OS sandbox per tenant. The worker host remains trusted.

Private pipes accept start, heartbeat, state-ack and stop commands. Status frames contain bounded metadata. State frames carry private node material and must never reach logs or APIs. The parent encrypts and commits each snapshot before acknowledging its strictly increasing sequence. Vault ownership binds the organization, connection and personal owner. Node and login envelopes share one key version and rotate together with `vault-rotate`; an empty record uses the current key for its first write.

Only the current lease and policy generation can write state/status. Lease comparisons use PostgreSQL `clock_timestamp()`, so a transaction that started before expiry cannot keep writing with stale time. Leases last 15 seconds, parent authority checks run about every three seconds, and the child has an eight-second heartbeat watchdog using monotonic elapsed time. Fatal control failure terminates the child independently of blocked startup, output or shutdown; the watchdog remains armed through graceful Stop. Database callbacks and pipe writes have deadlines. The parent renews/checks the lease before sending restored identity to a newly spawned child. These deadlines are not a measured production revocation SLO.

## Pause, revoke and erasure

Pause increments policy generation, withdraws the live attempt and preserves encrypted identity for explicit resume. Revoke first commits the deny, increments generation, clears the login link/peer snapshot and schedules cleanup. A stale child cannot overwrite that policy. Local keys are erased only after its lease ends or the child stops.

Logout/close does not prove deletion from the Tailscale administration device list. After local erasure, a connection that had a node is marked **manual**: the user must remove the inactive node in Tailscale administration. A never-enrolled record with no identity can be **complete**. If node metadata remains without local state, cleanup still stays **manual**. This release has no provider-deletion verifier.

Membership removal revokes personal connections in the same transaction as membership/session teardown. Creation and removal share the account-erasure lock, followed by a fresh active-membership read. The same guard protects revealing an enrollment link. Parent organization locks precede child locks and queue foreign keys; nonblocking lock contention rolls back its savepoint and returns a retryable conflict.

Account/organization deletion refuses retained node/login envelopes or live leases. Revoke and finish local cleanup first. Account deletion also erases inactive private connection metadata. Organization identities remain organization-owned when their creator leaves. Keep restored database backups offline until old node identities have been reconciled, because restoring encrypted state can restore an old enrollment too.

## Deployment

1. Back up the database and vault keys together. Apply `0347_network_connections` after `0346_merge_t3_v1850`. It creates the empty connection table and widens the background-job pool check. Rehearse the DDL lock and constraint validation on `background_jobs`.
2. Build from the repository root with `backend/Dockerfile`. Its Go stage builds the pinned broker and generates target-specific dependency notices. The runtime installs `/app/bin/t3os-tailscale-broker` and `/app/licenses/tailscale-broker/`. The existing unprivileged user launches it; no extra capabilities or TUN mount are needed. Certificate/checksum verification remains enabled.
3. Deploy matching API, worker and frontend versions with `TAILSCALE_ENABLED=false`. Keep a `system` worker for the 15-second cleanup sweep. Explicit `WORKER_POOLS` configurations must add `network` on an appropriate worker. `WORKER_NETWORK_CONCURRENCY` defaults to 2 and permits at most 16. A separate worker can use `WORKER_POOLS=network` while another retains `system`.
4. Configure the existing production vault keys. Install the broker at the same configured path on API hosts (availability reporting) and network workers (execution). For native installs, follow the tagged build and notice-generation commands in `integrations/tailscale-broker/README.md`, and set `TAILSCALE_BROKER_PATH` to the resulting absolute executable path. Do not supply shared Tailscale state, auth keys or provider credentials to the worker.
5. Allow the Tailscale control/relay connectivity required by the deployment. Complete controlled acceptance using an explicitly authorized test tailnet before enabling `TAILSCALE_ENABLED=true` on API and network workers. Compose already reads backend/root env files; this feature needs no public port or extra compose service.

Availability checks the flag and local executable, not remote worker health. A missing network worker leaves attempts queued until expiry. Monitor queue delay, fixed error codes, lease loss, attempt age and pending/manual cleanup; omit login URLs, envelopes and private frames from diagnostics.

To disable admissions, turn the feature off and restart affected API/workers. Metadata stays readable and Pause/Revoke remain available. Keep the system worker running to erase stopped revoked identities and report manual cleanup while disabled. Downgrade refuses all retained connection rows and network jobs, including history. Do not force-drop them: use a reviewed forward fix or coordinated application/database restore.

## Verification and follow-up

Tests cover owner/session isolation, vault binding/rotation, URL validation/redaction, commit-before-ack, stale sequence/lease rejection, explicit admission, teardown fences, recovery and HTTP projection. PostgreSQL tests cover constraints and expiry inside an already-open transaction. Broker tests use synthetic nodes. The implementation PR records which checks actually ran and which remain open.

Before enablement, validate real sign-in and device approval, status refresh, key expiry/re-authentication, pause/resume, revoke, worker/database loss, membership removal, vault rotation and manual provider removal. Inspect the final image architecture and license bundle. Unit tests do not substitute for these live acceptance checks.

The next slice needs exact authorized target/service handles before carrying traffic. `tsnet.Dial` can fall back to ordinary host networking for non-tailnet destinations; adapters must restrict dialing to the selected peer's validated tailnet IP and approved service/port. Browser, SSH and file operations each require their own authority, cancellation and output-protection contract. No arbitrary destination dialer is included here.
