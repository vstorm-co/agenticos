# Tailscale connections and access to user devices

**Status: design proposal only; implementation is on hold.**

The user requested a detailed PR first and explicitly directed that no code be
written. This document records the proposed behavior, technical boundaries,
delivery sequence and acceptance criteria. It does not implement or enable
Tailscale, device control, credentials, network routes or deployment changes.

**Reviewed on:** 19 November 2026, Asia/Singapore.  
**Repository baseline:** [t3 at f1210f992e5f](https://github.com/t3grp/agenticos/commit/f1210f992e5ff915ebe982c6364b05b10ccb9088).  
**Release state:** proposed; no live Tailscale connection or device acceptance test
has been performed. A later explicit instruction is required to begin implementation.
Merging a design document, if separately requested, would not authorize implementation.

## 1. Problem and intended outcome

A user should be able to connect an existing Tailscale network to t3OS, choose
specific devices and services, and let authorized agents reach those destinations.
Useful cases include a private ERP website, an internal MCP server, files on a
server, and SSH access to a development machine.

Network connectivity and device control are different capabilities. Tailscale
provides connectivity to permitted services. File operations, command execution,
browser actions and screen control also require an appropriate destination service
or the existing paired desktop executor.

The proposed product keeps managed Browser, Computer and Files environments as
the default. Access to a user-owned device is an explicit, separately selected
connection. Connecting Tailscale does not grant access to the user's personal
browser profile, cookies, screen or filesystem.

### Decisions proposed for review

| Area | Proposed decision |
| --- | --- |
| Product location | Connections → Devices & networks, with separate paired-computer and Tailscale choices. |
| Initial enrollment | A dedicated connector node uses Tailscale's interactive device-login URL. |
| Isolation | A separate connector process/container, network state and identity for each owning scope, active organization and connection. |
| Personal ownership | Owner-only use in the initial release; personal credentials cannot be shared by publishing an agent or joining a room. |
| Organization ownership | Explicit connection use permissions plus target, action and agent restrictions checked for each initiating principal. |
| Routing | A trusted broker routes only to registered, authorized destinations. Application-wide private-address exceptions remain unchanged. |
| Initial protocols | Approved HTTP services, remote MCP, managed-browser traffic and ordinary SSH/SFTP. |
| Native device control | Reuse the existing desktop hub and consent model; extend target selection only in a later, separately validated work item. |
| Automation | Personal network access from schedules, anonymous widgets and API-only callers is outside the initial release. |
| Delivery | Documentation-only now; future implementation is divided into three dependent PRs after user authorization. |

## 2. Existing foundations and evidence

These are repository observations, not assertions about the running production
deployment.

| Existing area | Evidence at the reviewed baseline | Consequence for this proposal |
| --- | --- | --- |
| Desktop pairing | [Desktop documentation](https://github.com/t3grp/agenticos/blob/f1210f992e5ff915ebe982c6364b05b10ccb9088/docs/desktop.md) describes a per-device session and an outbound WebSocket to the device hub. | Reuse the hub, presence and revocation model instead of building a second native executor. |
| Folder and screen consent | The same document describes approved folders, access modes and separate screen consent. Windows currently offers read-only or full access. | Do not promise folder-contained command execution on Windows. Preserve the native permission boundary. |
| Personal and organization connections | [MCP documentation](https://github.com/t3grp/agenticos/blob/f1210f992e5ff915ebe982c6364b05b10ccb9088/docs/mcp.md) and [connection guidance](https://github.com/t3grp/agenticos/blob/f1210f992e5ff915ebe982c6364b05b10ccb9088/.claude/skills/mcp-connections/SKILL.md) distinguish member-owned credentials from organization resources. | Follow existing credential ownership, but define the additional network-use checks explicitly. |
| Current private-address exceptions | MCP documentation describes deployment-level private-host allowlists, whose reach is broader than one user. | Do not use those settings as the isolation mechanism for customer tailnets. |
| Permission model | [Permissions](https://github.com/t3grp/agenticos/blob/f1210f992e5ff915ebe982c6364b05b10ccb9088/docs/permissions.md) defines permissions, resource grants and active-organization checks. | Use permission-based services and resource resolution, not hard-coded role names or UI-only checks. |
| Secret storage | [Secrets](https://github.com/t3grp/agenticos/blob/f1210f992e5ff915ebe982c6364b05b10ccb9088/docs/secrets.md) requires owner-bound vault envelopes and secret references. | Enrollment credentials, destination credentials and node private state use the existing vault mechanism. |
| Sandbox routing | [Sandbox documentation](https://github.com/t3grp/agenticos/blob/f1210f992e5ff915ebe982c6364b05b10ccb9088/docs/sandbox.md) describes separate managed runtimes and their lifetimes. | A connector requires explicit adapters; connecting the API does not automatically connect every runtime. |

[PR #89](https://github.com/t3grp/agenticos/pull/89) is merged and establishes the
managed workspace controls: opening a pane does not start compute, published
capabilities remain authoritative, and room viewers cannot start environments.
Preserve those behaviors.

[PR #181](https://github.com/t3grp/agenticos/pull/181) is an open draft for
Agentes-style multiplayer rooms. Its stated scope retains restrictions on
local-device and personal-sandbox execution. This proposal does not assume that
shared rooms can already use personal devices. Recheck that PR and the then-current
authorization path before implementing room integration.

The desktop documentation primarily describes the computer running the desktop
chat. Selecting another paired computer from a web session is proposed work,
not an existing feature verified by this PR.

## 3. Scope and exclusions

### Initial product scope

- Enroll, identify, pause, reconnect and revoke a Tailscale connector.
- Select only authorized peers and explicitly registered services; display device
  identity, connection owner, reachability and supported operations.
- Attach private HTTP/MCP connections and managed browsers to the selected route.
- Add SSH/SFTP adapters with separate destination authentication and permissions.
- Surface policy denial, unavailable devices, expired enrollment and cleanup failures.
- Preserve an audit trail linking the initiating person, organization, agent, run,
  connection, target and operation.

### Deferred or excluded

- Changing the default managed environments or automatically granting local access.
- Importing personal browser sessions, passwords, cookies or arbitrary local files.
- A new native remote-control agent, or a replacement for the existing desktop hub.
- Enabling RDP, SSH, Tailscale or other services on a user's device automatically.
- Arbitrary port scanning, whole-LAN discovery, subnet routing, exit nodes, public
  Funnel endpoints, peer-to-peer relaying between customers, or a generic open proxy.
- Headscale/custom coordination servers in the first release.
- Personal-connection sharing, unattended personal-network routines, and automatic
  authority transfer between agents or room participants.
- Assuming that mobile operating systems permit arbitrary background desktop control.
- Application code, tests, migrations, dependencies, CI configuration, provisioning,
  merges, releases or deployment changes in this design PR.

## 4. Proposed user journeys

### Connect a personal Tailscale network

1. Open Connections → Devices & networks and choose Add Tailscale.
2. Explain that a t3OS-hosted connector will join the user's tailnet as a device,
   and show the owning account, organization and proposed connector name.
3. Only an explicit Connect action allocates the connector and begins enrollment.
4. Present a fresh Tailscale device-login link in the initiating user's session.
   Bind the enrollment attempt to that session and the exact connector.
5. After provider authentication, verify the actual tailnet and node identity.
   If an expected network was selected, a mismatch requires an explicit restart.
6. Show provider device approval and network readiness independently from successful
   authentication. Enrollment alone does not enable agent traffic.
7. Let the owner select permitted devices and define services, protocols and ports.
   Device presence alone does not imply permission to execute or read files.
8. Review the resulting destinations and agent access, then enable the connection.

The target device must already run Tailscale and the requested service. Access
through a subnet router is deferred. Enrollment does not install software on the
user's computer or reuse that computer's Tailscale credentials.

### Connect an organization network

An authorized manager creates an organization-owned connection, selects who may
use it, and restricts agents and targets. A customer administrator applies the
corresponding tailnet policy. The UI explains the service identity separately
from individual t3OS users.

The advanced enterprise option uses a customer-scoped, tagged OAuth Client and
only the required API scopes. Its credential is owned by that organization.
Sharing a personal connection is not a shortcut to creating an organization service.

### Use a connection from chat

The Browser, Computer and Files controls show the selected environment or device.
Opening, closing or restoring a pane changes presentation only. Explicit Start,
Connect, Test or an already-authorized tool operation starts the required work.

The user sees the target, owner, service, granted actions and live state before
starting. A remembered target or a Last view preview does not preserve expired
permission. Recheck authorization on the next operation.

Network and native device selections remain independent. A managed browser can
reach a private website without granting local screen control. An SFTP connection
can expose an approved directory without granting a shell. Changing one selector
must not silently change the others.

### Disconnect and recover

Pause denies new operations and stops its active routing sessions while retaining
the enrolled identity for an explicit reconnect. Revoke invalidates authority,
stops the connector and begins removal of the remote node and local secret state.

Display operational states such as Awaiting sign-in, Awaiting device approval,
Awaiting policy review, Ready, Paused, Offline, Policy denied, Reconnect required,
Revoking and Cleanup pending. Never equate an authenticated node with a usable
service or a stopped process with confirmed provider-side removal.

## 5. Enrollment and Tailscale identity

Use Tailscale's documented device-login URL flow for the first personal connector.
The [tsnet documentation](https://tailscale.com/docs/features/tsnet) describes this
flow when no auth key or trust credential is supplied. Tailnet device approval,
where enabled, still applies.

Each enrollment attempt has an unguessable identifier, bounded lifetime, one
initiating principal and one connector. A second browser tab cannot claim another
user's completed attempt. Cancellation and expiry stop the provisional runtime;
partial completion leaves a cleanup record rather than an untracked node.

The login URL is enrollment material. Deliver it only to the initiating user,
exclude it from model context, telemetry, transcripts and shared room messages,
and use the supported provider endpoint. The broker verifies completion through
its own node state, not through a client-submitted success flag.

The initial release uses persistent connector nodes for both personal and
organization connections. Preserve the node identity across ordinary idle periods
and restarts; explicitly select persistent registration on the enterprise OAuth
Client path instead of relying on its ephemeral default. Ephemeral/session-only
connectors are deferred.

Track node-key expiry separately and request reauthentication when required. Do
not create a new tailnet device on every chat turn. Node replacement is a new
enrollment decision and must not silently inherit the old node's grants. Persistent
nodes require the explicit provider cleanup described in section 11.

### OAuth choices

| Mechanism | Appropriate use | Boundary |
| --- | --- | --- |
| Normal device-login URL | Initial interactive personal enrollment. | The resulting node has the enrolling user's Tailscale identity and policy; t3OS must independently restrict what its agents can do. |
| OAuth App | Customer-specific authorization-code provisioning when required. | Current Tailscale documentation limits an app and consenting users to the same tailnet. A single global t3OS app cannot enroll arbitrary customer tailnets. |
| OAuth Client | Advanced organization-owned service provisioning. | Client credentials create tagged service identities; obtain them from that customer's tailnet and store them in its vault scope. |

The OAuth App flow is documented for one-time device provisioning; do not assume
a reusable refresh token, cross-tailnet consent, or public-client/PKCE support
without verifying the then-current provider contract.

Enrollment and administration are separate permissions. A basic device login does
not automatically provide API authority to list every machine, edit tailnet policy
or delete a node. Use the connector's authorized peer view where sufficient.
Request additional administrative scopes only for a specific optional feature.

Sources: [OAuth Apps](https://tailscale.com/docs/features/oauth-apps),
[device provisioning](https://tailscale.com/docs/features/oauth-apps/device-provisioning)
and [OAuth Clients](https://tailscale.com/docs/features/oauth-clients).

## 6. Architecture and isolation

The request path is: authenticated t3OS operation, application authorization,
connection-specific broker, Tailscale policy, destination service, and destination
authentication. Each stage can refuse the operation.

The proposed broker is a small service using tsnet. Run it in an isolated
process/container for each ownership scope, active organization and connection.
Each connection and its node are bound to exactly one organization context.

A personal connection is owned by its member and its credentials remain sealed
to that member, but its network enrollment is usable only in the organization
where it was created. Using Tailscale in a second organization requires a separate
connection, node identity and explicit enrollment, including any provider approval,
device quota and cleanup obligations. Do not reuse the first organization's node,
private state or proxy. This is intentionally stricter than the existing personal
MCP credential model.

A shared operating-system Tailscale interface, shared SOCKS listener or shared
node-state directory is not a tenant boundary. Do not expose the host network,
container engine socket, control API or another connector's storage to a runtime.
Only one runtime lease may own a node's mutable state at a time.

The broker accepts a server-issued operation context containing the exact
principal, organization, agent version, run, connection, target, action, policy
version and expiry. The model supplies neither credentials nor routing authority.
Transport authentication and replay protection bind the operation to that context.

For browser traffic, a session-specific proxy can route traffic through the
broker, but every connection is still checked against that session's destination
policy. Other agents, containers or browser sessions cannot reuse its listener or
authorization. The proxy is not a general network capability.

The [userspace networking documentation](https://tailscale.com/docs/concepts/userspace-networking)
explains SOCKS5/HTTP routing for applications. Adapters must explicitly route each
supported protocol and DNS lookup. Prevent direct egress, alternate proxy settings,
QUIC/UDP, WebRTC or subprocesses from bypassing the selected private route; unsupported
paths remain unavailable until their enforcement is demonstrated.

## 7. Authorization and multiplayer behavior

Every operation must satisfy all relevant boundaries: active organization,
authenticated initiating principal, resource access, published capability and
organization scopes, connection permission, target/action policy, current approval,
Tailscale policy, destination authentication and native consent where applicable.

| Actor or context | Initial behavior |
| --- | --- |
| Personal connection owner | May configure and use their connection where the active organization permits it. Agent and target restrictions still apply. |
| Another member of the same organization | Cannot inspect or use another person's personal connection. |
| Organization connection user | May use only the connection, targets and actions that their effective permissions and operational policy permit. |
| Connection manager | May administer permitted organization resources. Administrative visibility is not personal-device consent. |
| Room reader | Cannot start an environment, probe a device or invoke a connection. |
| Room writer or agent mention | Creates no new device permission. Authority is resolved from the human initiating that run. |
| Delegate or resumed run | Retains the original initiating identity and may only narrow its target/actions. Revalidate current access. |
| Anonymous widget, unlinked channel sender or API-only caller | Cannot select a personal network connection in the initial release. |
| Schedule or background routine | Personal network access is deferred; existing desktop routine behavior remains unchanged. |

Use the permission catalog and resource-grant services. Preserve the existing
rule that a resource grant widens role-based resource access; implement operational
destination/action constraints as separate conjunctive checks. Do not attempt to
narrow an administrator's role by omitting a resource grant.

Current organization MCP sharing determines who can select a server; a published
agent can use its bound server for other authorized callers. A Tailscale connection
adds a distinct execution-time check for the initiating principal. Do not borrow
the publisher's connection, room owner's identity or another participant's device
when the current sender has no permitted route.

Personal connections are available only to their owner's private interactive runs
in the initial release. Shared-room runs cannot select or invoke them, even when
the owner authored the message. Personal results remain in owner-authorized
destinations. Do not insert private device files, screenshots or credentials into a shared
transcript merely because the run began in a room. Shared-room use of organization
resources requires an explicit output audience; personal-device room output stays
unavailable until a separate sharing design is approved.

Revocation, membership removal and grant expiry must affect new operations and
active sessions. Cached authorization is bounded by a short lease and policy
version; agent publication or a remembered UI selection never freezes access.

## 8. Destination policy, DNS and private-address validation

An approved destination records its tailnet identity, stable device identifier,
service name, protocol, exact host/origin, permitted ports and allowed operations.
A display name, a MagicDNS hostname or an address alone is not sufficient to
identify a device after replacement or re-enrollment.

Resolve names in the selected connector's network context. Associate the resolved
address with the approved peer and pin that result for the connection. Revalidate
on reconnect, DNS changes and device identity changes. Customer tailnets can use
overlapping address ranges, so caches and connection pools include the connector
and organization identity.

Do not permit all private ranges, all Tailscale addresses or all ports merely
because a connection exists. Broad default tailnet policy is possible; the trusted
broker and runtime egress controls must enforce selected destinations even when
the provider network allows more.

Loopback, cloud metadata, link-local addresses, t3OS infrastructure and another
tenant's resources remain inaccessible through this feature. A separately designed
native loopback service grant remains part of the desktop path, not a Tailscale
exception.

Validate redirects, OAuth discovery and token endpoints, browser subresources,
WebSockets, downloads and reconnects. A private service can use a separately
approved public identity provider, but enrollment does not authorize every host
named by that service. Preserve TLS verification, the original approved host/SNI,
origin-bound credentials and existing URL sanitization rules.

Do not solve private routing by expanding OUTBOUND_PRIVATE_ALLOWLIST or
MCP_ALLOWED_HOSTS. The new route is selected by an authorized connection reference;
unrelated public connectors keep their existing validation behavior.

Network policy narrows network reach; application permissions still need their
own implementation. A port being reachable cannot enforce file read-only access
or make an arbitrary command safe.

Sources: [Tailscale grants](https://tailscale.com/docs/features/access-control/grants),
[default ACL behavior](https://tailscale.com/docs/features/access-control/acls)
and the pinned t3OS MCP documentation in section 2.

## 9. Protocol and operating-system boundaries

| Capability | Adapter and prerequisites | Permission boundary |
| --- | --- | --- |
| Private HTTP/API | Selected service reachable through its connector; TLS or explicit supported HTTP configuration; destination credential where required. | Approved origin and operations; HTTP GET alone is not proof that an application operation is read-only. |
| Remote MCP | Existing remote MCP protocol support plus connection-specific transport. | Existing tool allowlists and approval behavior remain; network access adds no tool authority. |
| Managed browser | Per-run browser route through the authorized broker. | Domain/origin policy applies to navigation and subresources. No personal browser profile import. |
| SSH commands | Ordinary SSH server, selected account and verified host key. | SSH permission is separate from file access. A shell is not described as read-only based on command text filtering. |
| SFTP files | SFTP service and a restricted destination account or verified server-side directory boundary. | Read and write grants are separate; prevent path, symlink and junction escapes at the enforcing endpoint. |
| Native computer | Existing paired desktop executor and supported OS permissions. | Native screen consent and stop/takeover behavior remain mandatory. |
| RDP/other remote desktop | Separate future integration with its own supported host service and authentication. | Tailscale alone does not implement screen capture, input or session consent. |

Native Tailscale SSH is not the first cross-platform command adapter. Its server
supports Linux and specific macOS installations, not Windows. Tagged source nodes
also have Tailscale SSH identity restrictions, including access to user-owned
destinations. Ordinary SSH over Tailscale is a separate option and needs its own
credentials and host verification.

The existing desktop documentation offers read-only and full access on Windows;
a folder-contained command mode must not be displayed there without a verified
enforcement mechanism. SFTP directory restrictions depend on the destination
server, not on Tailscale.

Sources: [Tailscale SSH](https://tailscale.com/docs/features/tailscale-ssh),
[tagged identities](https://tailscale.com/docs/features/tags),
[Windows RDP](https://tailscale.com/docs/solutions/access-remote-desktops-using-windows-rdp)
and the pinned desktop documentation.

## 10. Logical records and integration contracts

These are proposed concepts, not database migrations or finalized API schemas.

| Record | Information to retain |
| --- | --- |
| Network connection | Opaque id, personal/organization ownership, exactly one organization context, provider, its own tailnet/node identity, status, policy version and vault references. |
| Enrollment attempt | Initiating user/session, connection, expected network where known, attempt generation, expiry, result and cleanup state. |
| Device/service target | Connection id, stable peer identity, display label, supported protocol, exact destination, ports, approved account/path where applicable and credential reference. |
| Operational grant | Eligible principals/groups, published agents, targets, actions, expiry and approval requirements. |
| Runtime lease | Owner scope, active organization, connection, worker identity, node-state generation, lease expiry and policy generation. |
| Operation/session | Initiator, agent version, run/conversation, target/action, authorization generation, start/stop state and result classification. |
| Cleanup record | Removed connection/node identity, pending external cleanup, retries and evidence of completion; no reusable access authority. |
| Audit event | Actor, organization, connection/target ids, action, decision, timestamp and outcome without payloads or secrets. |

Follow Routes → Services → Repositories. Collection routes use permission gates;
per-resource decisions belong in services through resource access resolution.
Queue durable provisioning and cleanup through the existing transaction-aware
background-job mechanism.

The implementation should expose operations for enrollment, status, target
registration, explicit testing, grants, pause/reconnect/revoke and session inspection.
Finalize endpoint names and versioned contracts during implementation review.
No source schema, route, permission identifier or migration is created here.

Published agent specifications should reference capabilities and authorized
organization resources, or resolve each person's own connection at run time.
Never export personal connection identifiers, enrollment URLs, node keys or
destination secrets in an agent spec.

## 11. Credentials, lifecycle and revocation

Use the existing vault envelope mechanism and ownership scope for OAuth credentials,
auth keys, SSH credentials and persistent Tailscale private state. Node state is
credential material even when Tailscale represents it as files. Keep runtime
material in its isolated temporary storage and persist it only through the approved
owner-bound mechanism; implementation must verify the supported tsnet state-store
interface and atomic update behavior.

Provisioning-key expiry or deletion is not treated as removal of a node already
enrolled. Rotation, node-key expiry, tailnet removal, credential revocation,
connection pause and connection deletion are distinct events. See Tailscale's
[auth-key lifecycle](https://tailscale.com/docs/features/access-control/auth-keys).

A revoke operation first commits a new authorization generation that blocks
admission. It then terminates broker streams and runtime leases, attempts provider
logout/removal using supported authority, clears local private state, and records
any remaining provider cleanup. A basic device-login connection may need the
owner to remove its node in the Tailscale console if no removal API credential
exists; show that limitation explicitly.

Proposed release targets are immediate refusal of new operations after revocation
commits and closure of active broker streams within five seconds under normal
service conditions. A lost control connection must expire authority within a
bounded lease, proposed at no more than fifteen seconds. These are acceptance
targets to validate, not measured behavior.

Closing an SSH stream cannot guarantee termination of detached processes or undo
completed writes on a destination. Native executor cancellation must follow its
documented process-tree behavior. Record uncertain outcomes and do not replay
side-effecting operations automatically after a timeout or worker crash.

An offline device produces an explicit unavailable state. A run never switches
to another device, uses the cloud machine's local path, or falls back to a public
route to complete a private operation. Routine retries and reconnects revalidate
identity and authority.

## 12. Operations, visibility and cost

Separate connector enrollment, runtime readiness, peer presence, policy permission
and application health. A peer being online does not prove that its selected service
is reachable or authenticated. Explicit Test probes only the selected service.

Bound concurrent sessions, transfer sizes, connect/read deadlines, enrollment
attempts and idle lifetimes. Use backoff for provider failures and rate limits;
do not create a new node to avoid an error. Determine deployable resource limits
from a measured prototype before enabling the feature for customers.

Retain metadata needed for access review and troubleshooting. Connection activity
can identify the device, action and result; secrets, full URLs containing tokens,
file contents, screenshots and command output follow the existing protected
artifact/transcript paths and their audience controls.

Expose pause/revoke, active sessions and cleanup failures in the connection's
management view. An organization can disable the feature for its runs; operators
can disable connector admission and terminate affected runtimes during an incident.

Connector compute and Tailscale devices have operational cost and provider plan
limits. Verify commercial terms, quotas and the chosen deployment's resource use
before release. This design assumes neither unlimited free nodes nor zero hosting
cost.

## 13. Future implementation sequence

**All work below is unstarted and blocked on a later user instruction to implement.**

| Future PR | Deliverables | Exit gate |
| --- | --- | --- |
| A: Connections and enrollment | Ownership model, vault integration, isolated broker lifecycle, device-login flow, selected peer inventory, target policy, status, pause/revoke and audit metadata. | Isolated test tailnets demonstrate correct enrollment, identity, policy refusal, cleanup and cross-user/cross-organization denial. |
| B: Private service adapters | Private HTTP/MCP routing, managed-browser transport, ordinary SSH/SFTP, destination credentials and protocol-specific permission enforcement. | Each adapter passes allowed/denied cases, DNS/redirect tests, browser bypass tests and revocation tests. |
| C: Device selection and native integration | Environment/device selector, reuse of desktop presence/consent, private output handling and any permitted multiplayer integration. | Supported OS acceptance, explicit native consent, selected-device accuracy and room audience isolation are verified. |

Rebase and reconcile with the then-current managed workspace controls, PR #181
and device-hub changes before starting each stage. Do not replace unrelated
capabilities, approve local access by migration, or silently enable the feature
for existing accounts.

Rollout should begin disabled, then use operator-owned test networks, then
explicit pilot organizations. Deployment and rollback plans must identify exact
images, schema compatibility, credential cleanup and outstanding node cleanup.
Disabling admission must stop new network work without deleting ordinary chat
history or unrelated managed workspaces.

## 14. Acceptance criteria for implementation

Every item below is a future gate, not a completed test.

### Enrollment and user experience

- [ ] Merely viewing Connections or opening a pane creates no connector and starts no compute.
- [ ] Enrollment is bound to the initiating user, active organization and exact attempt; stale, cancelled or cross-account completions fail.
- [ ] Tailnet/node identity is verified; wrong-network enrollment is refused or explicitly restarted.
- [ ] Authentication, device approval, policy readiness and service health have distinct states.
- [ ] Device replacement or a changed node identity requires target review.
- [ ] Restarting an authorized connector preserves its intended identity without creating duplicate nodes.

### Isolation and authorization

- [ ] Two users in the same organization cannot access each other's personal connection, state, peer list or proxy.
- [ ] Two organizations with overlapping Tailscale addresses cannot cross-route or share cached destinations.
- [ ] A user in multiple organizations needs a separate connection/node enrollment in each; neither node state nor operational grants can cross organization contexts.
- [ ] Unprivileged runtimes cannot read node state, reach broker control endpoints or bypass the authorized proxy.
- [ ] Resource grants, organization scopes, target/actions and agent restrictions are all enforced server-side.
- [ ] A room reader, mention, delegate, retry or agent switch cannot borrow another participant's authority.
- [ ] Shared transcripts and previews do not expose personal device output.
- [ ] Membership removal, grant expiry and node removal invalidate subsequent operations.

### Network and protocol behavior

- [ ] A broadly permissive tailnet still cannot be used to reach an unselected target or port through t3OS.
- [ ] DNS rebinding, stale peer mappings, IPv4/IPv6 variants, redirects and OAuth endpoint changes cannot widen access.
- [ ] Metadata, loopback, t3OS infrastructure and another tenant's network remain blocked.
- [ ] Browser subresources, WebSockets, downloads and alternate network paths obey the same route policy.
- [ ] Public connections retain their existing private-address protection.
- [ ] SSH verifies the selected host and account; SFTP write permission is separate from read access.
- [ ] Read-only file access cannot launch a shell; paths and symlinks cannot escape the enforced directory.
- [ ] Windows is offered only supported native modes, with separate screen consent.
- [ ] Native Tailscale SSH restrictions are surfaced; ordinary SSH is tested independently.

### Lifecycle and resilience

- [ ] Revocation blocks new calls after commit and meets the measured stream/lease shutdown targets.
- [ ] Provider cleanup failures remain visible and retryable; no false claim of node removal is shown.
- [ ] Expiring an enrollment key is not mistaken for revoking an enrolled device.
- [ ] Offline targets and expired credentials fail explicitly without substitution or public-route fallback.
- [ ] Timeouts and crashes do not automatically repeat uncertain commands or writes.
- [ ] Logs, traces, API responses and exported specs contain no secrets or enrollment material.
- [ ] Resource limits, idle behavior, audit retention, cleanup and recovery are exercised under concurrent use.

## 15. Decisions to close before implementation and release

| Decision | Proposed direction | Evidence required |
| --- | --- | --- |
| Production baseline | Implement against the current t3 branch, then plan deployment against the actual running version. | Current deployment inventory; this PR does not establish it. |
| tsnet packaging and persistence | Isolated small Go broker using the existing vault for private state. | Supported SDK state-store and clean shutdown behavior, pinned versions and resource measurements. |
| Personal versus service identity | Interactive personal enrollment first; customer-owned tagged clients for enterprise services. | Provider policy and quota checks; narrow required API scopes. |
| Provider cleanup without API credentials | Best-effort supported logout plus explicit pending/manual removal state where required. | Verify exact provider semantics and demonstrate both reachable and unavailable control-plane cases. |
| Browser routing support | A session-specific authenticated proxy with enforced egress policy. | Prove complete browser-path coverage before exposing the option. |
| Room and remote native-device use | Preserve current restrictions until explicit identity and output-audience checks are accepted. | Reconcile with PR #181 and native consent behavior on supported OS versions. |
| Performance and quotas | Bounded sessions and idle runtimes with visible operational costs. | Measured CPU/memory, enrollment churn, concurrency and current Tailscale commercial limits. |

## 16. Validation of this design PR

This PR changes documentation only. It adds this repository-only design note and
a topic-map entry in AGENTS.md. The existing MkDocs configuration excludes
design notes from the published site, so this proposal does not advertise an
available feature and needs no product-page translation or navigation change.

Review must verify the document's source links, ownership model, permission
boundaries, explicit implementation hold and documentation-only file diff.
Application tests, live device enrollment, network probes, provider credential
creation and deployment validation are intentionally not part of this PR.
