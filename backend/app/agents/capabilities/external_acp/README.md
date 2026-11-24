# External ACP agent

A separately selectable delegation capability reusing the coding agent's Desktop
ACP pipe, session isolation, budget admission, streaming, cancellation and unpriced
usage records. It adds no background queue or A2A service.

Only a local registration ID is stored in the published spec. The Desktop owner
registers an absolute program path and argument array and approves native launch.
No command, environment, credential or account token comes from the server. The
program manages its own login and model; changing that account requires removing
and registering it again to discard continuation state.

Custom programs run with local account access. Read-only confinement is not
claimed; enable Human approval to ask before handing over each task. ACP native
tools belong to that program; platform tools are not forwarded. Unsupported ACP,
login requirements and missing programs fail explicitly. A session is resumed
only when the program declares support. This is delegation, not a primary runtime.


## Antigravity

The Desktop setup template registers `agy acp` with Google personal sign-in.
The Desktop process strips inherited Gemini API keys and the server selects the
advertised `oauth-personal` ACP method before creating or loading a session.
It never falls back to another method. Google login remains in the CLI; no
Antigravity token files are imported into AgenticOS.

`inspect_acp_agent` opens an approved session without an inference prompt and
reads bounded model/thinking choices from `configOptions`. Missing settings are
distinct from an empty list. `model_id` applies an explicit runtime choice; an
unsupported model setting fails. Choices are account/session-specific, not
proof of subscription entitlement, quota or third-party model availability.

Official protocol reference: https://antigravity.google/docs/ide/extensions/acp
Real-account login, quota, revocation and restart acceptance remain pending.
Platform tool forwarding and primary conversation runtime are separate work;
this capability currently delegates using the external program's native tools.

Cursor account registrations require `cursor_login` and remove API/auth-token
overrides in the native child. Cursor human questions and plan approvals return
`cancelled` and stop delegation until the person reviews them in the CLI.
Known whole-chunk account/billing failures must not become successful end turns;
the patterns are based on OpenBot's observations of Cursor 2026.10.22-27dcf5f
([source](https://github.com/nightly-labs/openbot/blob/82f897328826ad425dd3e2d2ac710340bbdf0cbd/src/backend/acp-flavor.ts#L799)).
They are not a general parser for error-like prose. API-key registration remains
pending verification of a supported isolated credential-store contract.

Cline uses direct foreground `cline --acp`, fixes `CLINE_PROVIDER=cline`, and
separates the `cline` account method from an explicit inherited API key. Key
mode requires a nonempty Desktop-process `CLINE_API_KEY` before spawning and
skips account authentication; account mode removes the inherited key. No token
is stored by AgenticOS or sent through server messages. CLI contract checked at
[`eff43e19b267`](https://github.com/cline/cline/blob/eff43e19b267e171f597ab03733bfed25090f72d/apps/cli/src/acp/acpAgent.ts):
provider override cannot change during a session, the environment key wins over
restored credentials, and the direct ACP process owns its session managers.

Mistral Vibe supplies `browser-auth` and `_auth/status`; the status is reduced to
API-key source and native sign-out availability, never account identity, key,
endpoint or raw config errors. The shared task loop accepts an injected credential
probe rather than importing vendor transport logic. A probe's refusal ends before
inference and still uses the task's deadline and cleanup. The native child enables
the experimental catalog and disables telemetry without rewriting CLI files.
The contract was checked in [Vibe 3.1.3 source](https://github.com/mistralai/mistral-vibe/tree/63dab302305c80131ea1e5b1c3cb18c2a4fd96d3/vibe/acp).
Remote delegated browser login and a native vendor sign-out control remain separate
from this device-owned registration; removing an ID revokes its running tasks,
not a key owned by Vibe or its launch environment.

Selected Pi vault-key modes are optional and separate from CLI-owned login. The
initiating member must have independent vault visibility, a private audience
and their own full-access device. Native templates force an isolated Pi 1.5.2
configuration and fixed provider authentication. Only the exact acknowledged
provider/model may receive a prompt. Plaintext crosses only the authenticated
native launch; reports and live tool activity are redacted, and fragmented text
is retained until the complete answer can be screened. Key rotation changes
continuation identity. See `docs/desktop.md#pi-vault-key` for setup and limits.
