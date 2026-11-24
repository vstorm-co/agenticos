# Install the accounting firm pack

Use this pack in any t3OS organization. The manifest lists the exact local skills
and agent templates selected for installation. The installer reads those checked-in
files; it never downloads upstream repository content while installing.

The default is a read-only preview. Applying creates organization-visible skills
and **draft agents**. It does not publish an agent, start a run, install software,
provision a sandbox, connect an accounting system, or change existing instructions.

## Prerequisites

- Python 3.12 or later and PyYAML 6. The backend already declares PyYAML; a separate
  environment can install it with `python -m pip install 'PyYAML>=6,<7'`.
- A t3OS deployment with the public API contract in this repository, including
  AgentSpec version 14. The installer compares complete specs against that version's
  verified defaults and stops on a changed contract instead of ignoring new fields.
- An organization API key issued in **Settings → API**, or a session access token.
  Set it in the process environment as `T3OS_API_TOKEN`; do not put it in command
  arguments, source files, or this manifest. The installer uses
  `Authorization: Bearer <token>`, not the deployment service's `X-API-Key` scheme.
- The exact organization UUID and an organization model profile UUID. Find the
  profile in the Builder or the public `GET /api/v1/providers/model-profiles` API.
  The selected profile must be chat-capable and have usable authentication.
- `skills:view` and `agents:view` with `all` scope, so the preview can inspect every
  possible name collision. Applying additionally needs `skills:edit` and
  `agents:edit`. The API still checks authorization for every individual request.

For organization keys, both the issuer's permissions and the key's issued scopes
must allow these operations. The installer sends `X-Organization-Id` on every
request and verifies the actual active organization through
`GET /api/v1/me/permissions` before reading inventory and again before writing.

## Check the bundled files

From the repository root:

```bash
python integrations/accounting-firm/install.py --check
python -m unittest discover -s integrations/accounting-firm -p 'test_*.py' -v
```

The local check validates the explicit manifest, template skill references,
capability binding structure, names, UTF-8 resources, and portable paths. It does
not contact a deployment or prove that a model, sandbox, OCR engine, or connector
is operational. The unit tests mock the API and need no database or backend import.

## Preview the exact organization

Set `T3OS_API_TOKEN` securely in the current process environment. Replace the
example host and UUID placeholders below with the intended deployment values:

```bash
python integrations/accounting-firm/install.py \
  --base-url https://your-t3os.example \
  --organization-id ORGANIZATION_UUID \
  --model-profile-id MODEL_PROFILE_UUID
```

The base URL excludes `/api/v1`. HTTPS is required except for loopback development.
Redirects are refused, so use the deployment's direct API origin rather than a URL
that redirects to a login page or another hostname.

The JSON preview identifies each skill and agent as unchanged or to be created.
For a matching partial skill it lists only the missing resources. It also reports
each template's `attach` requirements and suggested MCP connections. Neither is
automatically provisioned or bound.

To select one or more roles, repeat `--agent` with keys from `manifest.json`:

```bash
python integrations/accounting-firm/install.py \
  --base-url https://your-t3os.example \
  --organization-id ORGANIZATION_UUID \
  --model-profile-id MODEL_PROFILE_UUID \
  --agent finance/AGENT_TEMPLATE_KEY
```

A selection installs only the named agents and their required skills. Without a
selection, the complete manifest is used. `--agent` also works with `--check`.

## Create the reviewed drafts

Run the same preview command with these two additional arguments:

```bash
  --apply --confirm-organization-id ORGANIZATION_UUID
```

The confirmation UUID must exactly repeat the target organization's UUID.
Preflight checks all existing content before the first write. Skills are created
first, their text resources next, and agents last with the actual returned skill
UUIDs. Successful output includes the installed skill and draft agent UUIDs.

Inspect each draft in the Builder, attach the required client evidence and
authorized connections, configure the intended runtime, and run the platform's
draft validation before publishing. In particular, `attach: sandbox` states a
requirement; it does not create an execution environment. An OCR procedure does not
install OCR software. This installer also leaves delegation unbound: pinned
subagents require actual published specialist version UUIDs and separate review.

## Resume an interrupted install

Rerun the preview with the same pack files, organization, model, and selection.
Then rerun with `--apply` after reviewing it. The installer does not retry a failed
POST automatically because the server may already have committed the request.

It matches exact skill names and agent names/handles, checks their content, and
reuses their actual UUIDs. It can finish a partially created skill by adding only
absent resources, including when the server committed a write whose response was
lost. Existing matching draft agents are left untouched.

There is no overwrite, delete, publish, or upgrade mode. A changed body, resource,
agent spec, audience, model, category, tag, published/archived state, or an ambiguous
match stops the install for manual review. Extra resources also count as a
customization. Do not remove or rename organization content just to bypass a
conflict; review whether to keep the existing customized version or prepare a
separately named pack.

Only one installer should operate on a given organization at a time. Concurrent
organization edits can invalidate a preview; list changes and API conflicts stop
the run. A multi-request install is not transactional, so a later failure can
leave earlier skills or drafts created. The next preview shows that partial state.

## API contract references

The implementation follows these repository sources:

- `docs/api.md`: bearer authentication and organization selection.
- `backend/app/api/routes/v1/permissions.py`: the active organization and permissions.
- `backend/app/api/routes/v1/skills.py` and `backend/app/schemas/skill.py`: paginated
  skill listing, individual resource reads, and create-only resource requests.
- `backend/app/api/routes/v1/agents.py` and `backend/app/schemas/agent.py`: paginated
  agent listing including archived rows, draft reads, and draft creation.
- `backend/app/api/routes/v1/model_providers.py`: organization model discovery.
- `backend/app/agents/spec.py`: explicit AgentSpec and capability binding defaults.

The defaults were checked on 2026-11-10 against the real Pydantic `AgentSpec`
serialization from source blob `cd985611b22056350d48b7642fac3abac7d13363`.
Both the installer's complete spec and a minimal spec expanded by the server's
defaults produced the same 29-field JSON object. The actual `AudienceChoice`
model from blob `fe55214660a0f696688d519828eefb974375a821` also accepted
`visibility: org` with empty group and user grants. This isolated schema check used
the real spec and required value classes, with postponed annotations for Python
3.12; it did not run the backend, database, or a live deployment.

The create service was also inspected: supplied nonblank instructions, an explicit
model UUID, `from_starter: false`, and selectable capabilities avoid its automatic
starter/model substitutions. Server uniqueness constraints on organization/skill
name, skill/resource name, and organization/agent slug reject concurrent duplicate
creates. A refused or uncertain POST stops this installer; the next preview reads
the resulting state rather than retrying that request blindly.

Adding these files to the repository catalog makes them available in the gallery
after the next application deployment. The API installation path above can create
the adapted content in an existing compatible deployment without redeploying it.
