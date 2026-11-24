# Tailscale lifecycle broker

This standalone Go child process, run by the parent worker, owns one tsnet server
for one user, organization context and connection. The parent must not share the
process or its node state across organizations. The broker uses a custom
in-memory ipn.StateStore; every state update is sent to the parent and WriteState
waits until the parent acknowledges persistence. The parent is responsible for
encrypting the snapshot with the owning vault identity.

The child process is intended to run inside its dedicated worker. It uses
Tailscale userspace networking, with no TUN device, application listener, Loopback API,
SOCKS5 endpoint, arbitrary dial RPC or API-wide proxy. It exposes only the
private stdin/stdout JSON-lines protocol described below. The parent should
continue to enforce per-user, per-organization and per-connection lifecycle
limits.

## Pinned toolchain

The tailscale.com dependency is pinned to v1.104.7 and the module requires Go
1.27.4. Docker pins its build-stage toolchain to Go 1.27.4.

## Protocol

The first stdin line is a strict v1 start frame:

~~~json
{"version":1,"type":"start","connection_id":"123e4567-e89b-12d3-a456-426614174000","hostname":"broker-1","mode":"enroll","state":{}}
~~~

State is a map from Tailscale state keys to standard base64 values. The broker
accepts at most 1 MiB per line, 256 keys, 256 bytes per key and 512 KiB of
decoded state. Initial state never goes to a local persistent store.

Each subsequent parent line is exactly one of:

~~~json
{"type":"heartbeat"}
{"type":"ack","sequence":1}
{"type":"stop"}
~~~

An acknowledgement may also include ok:false or a non-empty error to refuse
persistence. Any refused, mismatched or missing acknowledgement fails closed.
The parent sends heartbeats every 3 seconds, including during graceful shutdown
after `stop`. The child terminates if it receives no heartbeat for 8 seconds,
leaving margin below the parent's 15-second lease. State acknowledgements must
arrive within 5 seconds. EOF and malformed or oversized frames close the node.

Status and error events contain only sanitized DTOs and fixed codes. State events
carry the base64 private node state to the parent so the parent can encrypt it
with the owning vault identity. No protocol event includes public keys, user
profiles, peer API URLs, provider error text or diagnostics. An auth_url is
included only when it is an HTTPS URL on the exact host login.tailscale.com,
uses the default port or 443, has a path beginning `/a/`, contains only
printable ASCII, and is at most 4096 bytes; userinfo and fragments are rejected.

Enroll starts Tailscale's interactive login flow only when backend status is
NeedsLogin. A restored identity in Starting, Stopped or another transitional
state is allowed to resume without prompting for a new login. Enrollment
completes when status reports Running with both a stable node ID and tailnet
identity, or after 10 minutes. Status polls for 20 seconds. Logout attempts local tsnet
logout, but a successful local logout is not evidence that the remote device
was deleted from the tailnet. The product must retain manual/provider-side
cleanup state where removal is required.

## Local checks

Tests use fake node implementations and protocol pipes; they do not enroll a
device, use provider credentials or access a live tailnet.

The broker build uses Tailscale's source-defined `ts_omit_webclient` tag. The
broker does not expose Tailscale's web UI, and this tag removes the embedded
web-client assets and their `web-client-prebuilt` module from the target build.
The module remains in Tailscale's full `go.mod` dependency graph.

From this directory, use the pinned Go toolchain in a fresh PowerShell session.
The build below produces the Linux/amd64 deployment binary. Clear the cross-build
target before running the collector itself on the host; its arguments select the
deployment target for the inventory.

~~~powershell
go test -tags=ts_omit_webclient ./...
go vet -tags=ts_omit_webclient ./...
$env:CGO_ENABLED = "0"
$env:GOOS = "linux"
$env:GOARCH = "amd64"
go build -tags=ts_omit_webclient -o t3os-tailscale-broker .
Remove-Item Env:GOOS, Env:GOARCH
go run ./tools/license_inventory.go -tags=ts_omit_webclient -goos linux -goarch amd64 -output licenses
Remove-Item Env:CGO_ENABLED
~~~

The license inventory command writes `THIRD_PARTY_NOTICES.md`, copies
recognized dependency license and notice texts under `dependency_licenses/`,
and includes the Go distribution and standard-library vendored notices under
`go-toolchain/` inside the selected output directory. Pass the same GOOS and
GOARCH as the broker build so the report records the runtime dependency
closure for that target. It exits unsuccessfully when a runtime module has no
recognized license or notice file, after writing the report for manual review.
This inventory is not a complete legal audit.
