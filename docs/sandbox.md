# The sandbox

A container an agent can write files in and run commands in. It is how a run
reads the spreadsheet somebody attached, plots something, clones a repository, or
keeps notes between messages — and it is the one part of this platform that runs
code nobody in this repository wrote.

This page is the whole picture: what runs where, what a session is, which
environments an agent may ask for and how to change them, what isolates one
organization from another, and how long any of it survives.
`configuration.md#the-sandbox-service` is the variable-by-variable reference.

## What runs where

Three processes, and the arrangement is the security model:

```
agenticos_backend  (container)  ──HTTP──▶  agenticos_sandboxd  (container)
   no docker.sock                             /var/run/docker.sock  ──▶  the host's Docker daemon
                                                                              │
                                              a session's container  ◀────────┘
                                              (a sibling, not a child)
```

- **The API container holds no Docker socket.** That is the whole reason
  `sandboxd` is a separate service rather than a library call: running a container
  requires the daemon, and reaching the daemon is equivalent to root on the host.
- **`sandboxd` holds the socket and asks the *host's* daemon** to start a
  container. So a sandbox is a **sibling** of `sandboxd`, not a container inside
  it. There is no Docker-in-Docker here, nothing is `--privileged`, and no nested
  daemon runs.
- Which is why the workspace directory is bind-mounted **at the same path on both
  sides**: `sandboxd` creates it, then asks the daemon to mount it, and the daemon
  resolves that path on the host. A named volume, or a path existing only inside
  the `sandboxd` container, is refused with `mounts denied`.

`sandboxd` is the server from [`pydantic-ai-backend`](https://github.com/vstorm-co/pydantic-ai-backend),
shipped as `ghcr.io/vstorm-co/sandboxd`; the backend talks to it over HTTP with
the token in `SANDBOXD_TOKEN`. The other two sandbox backends a spec can name —
`daytona` and `state` — are a hosted service and a document in Postgres, and
neither involves any of the above.

**The token is root-equivalent.** Whoever holds it can start containers on that
host. `make sandbox-token` generates one into `backend/.env` once and leaves it
alone afterwards, because regenerating it orphans every workspace the service is
currently holding. Treat it as the Docker socket it sits in front of — which is
also why the service's own dashboard is off (`SANDBOXD_UI_ENABLED: 0`): that page
asks a human to paste the token into a browser.

## A session, and what shares one

**One container per session, never one for everybody.** A session is identified
by a key the backend derives, and the key is what decides what is shared:

```
xc-4f2a91c8-7b3e5d10-9c1f…      backend · scope · organization · host · subject
^^                              `x` a container service, `d` a document; `c` the conversation scope
```

The scope is a field of the agent's spec — `run`, `conversation`, `channel`,
`user` or `agent` — so `conversation` (the usual choice) means one container and
one directory per chat, and `agent` means every run of that agent shares one.
Folded into the key as well: which **backend kind** and which **host** the
workspace lives on, because a `state` document and a container's volume are not
the same thing wearing different names, and neither are two `sandboxd`
installations. Registering a second host and marking it the organization's
default used to move every existing workspace without anybody editing a spec.

What separates one tenant from another:

- a **container of its own** and a **host directory of its own** per session;
- session keys are `uuid4`-derived, so they are unguessable — the readable
  organization prefix is for reading a dashboard, **not** the boundary;
- the organization check on every row that produces those keys, which is what the
  boundary actually is;
- `tenant` (the organization id) sent when the session opens, which the service
  counts against `SANDBOXD_MAX_SESSIONS_PER_TENANT` (10) inside a pool of
  `SANDBOXD_MAX_SESSIONS` (20) — so one organization cannot take the installation.
  Over the ceiling the service refuses with `already holds 10 of 10`.

## Which environments an agent may ask for

**One runtime ships, and it is defined in this repository** —
`backend/app/core/catalog/sandbox_runtimes.json`:

| | `workbench` — 1.93 GB, built in about 65 s on a warm host |
|---|---|
| Built on | `python:3.12-slim` |
| Languages | Python 3.12; Node 24.19.0 LTS with npm 11 and `tsx` for TypeScript |
| Tools | `git`, `curl`, `ripgrep`, `fd`, `jq`, `less`, `procps`, `unzip`, `zip`, `uv`, `pdftotext`/`pdfinfo` |
| Reading | **liteparse** (`lit`) — PDFs and images to text or markdown, OCR included; `poppler-utils` for the fast text-layer path and a page count |
| Documents | `pypdf`, `python-docx`, `openpyxl`, `python-pptx`, `reportlab`; **LibreOffice** headless for conversion and the legacy formats |
| Data | `pandas`, `duckdb`, `tabulate` |
| Charts and images | `matplotlib` (Agg), `pillow` |
| Web | `httpx`, `requests`, `beautifulsoup4`, `lxml`, `markdownify` |
| Other | `pyyaml` |
| Memory | 2 GiB |
| Network | yes — the only runtime that has one |

One rather than eight, and the reason is `prewarm`: the service builds **every**
entry of its allowlist when it starts, so eight aliases is eight `pip install`s in
a start-up nobody is watching, eight images cached on the host, and an agent asked
to read a PDF getting whichever alias its spec happened to name. `workbench` is
built to be the answer to *write and run some code, read what the user attached,
plot it, fetch a page*.

Until #1040 this catalogue was `BUILTIN_RUNTIMES` from the sandbox library:
fifteen recipes, of which a `sandboxd` started by this project allowed three. It
also meant that adding a package to one image was a release of a dependency, a
version bump and a pin.

### What is in it, and what is deliberately not

Measured on `python:3.12-slim` (205 MB), arm64:

- **liteparse comes from `pip`, and that is the whole answer.** The wheel is
  13.8 MB, carries the Rust binary and the `lit` CLI, has **no Python
  dependencies**, and bundles OCR — measured at 1.3 s for a one-page PDF with OCR
  and 79 ms for a PNG. So `cargo install` (a Rust toolchain), the npm package (a
  second copy of the same binary) and the WASM build (for browsers) all buy
  nothing here.
- **LibreOffice, at +683 MB, and it is worth it.** It buys three things nothing
  else here does: `lit` can read the legacy `.doc`, `.xls` and `.ppt` formats,
  which is what a business user actually attaches; `soffice --headless
  --convert-to pdf deck.pptx` renders a deck the agent built with `python-pptx`,
  which is how a presentation becomes something a person can open; and
  `--convert-to png` turns a slide into an image the agent can read back and
  *look at*, since `read_file` is multimodal here. About a second per document
  after the first. Writer and Calc are +135 MB of that 683 and are in for one
  reason: office conversion that worked for presentations and not for documents
  would be an exception in the product and an exception in the prompt.
- **It only works because the runtime is *built*.** LibreOffice creates a user
  profile on first run, so it needs a real account with a writable home — which
  the builder makes when `SANDBOXD_SANDBOX_UID` is set (`useradd --uid 10001
  --create-home`). Run the same image as a bare uid with no passwd entry and
  every conversion fails with `User installation could not be completed`. That is
  also why a ready-made `image` runtime cannot simply add LibreOffice: the two
  decisions are one decision.
- **Node from nodejs.org, not from apt.** Debian's `nodejs npm` is +398 MB and
  ships npm 9; the official tarball is +239 MB *and* current — and Node 20, which
  this recipe first pinned, has been end-of-life since April 2026. The arch is
  detected in the command, because the same catalogue builds on amd64 and arm64.
- **`poppler-utils` (+67 MB) beside liteparse, not instead of it.** `lit` is the
  better reader — layout, tables, markdown — and `pdftotext` is the faster one on a
  PDF that already has text: a 120-page book in under a second. `pdfinfo` is why it
  is really here, because a page count in milliseconds is what turns "extract this
  book" into a plan.
- **OCR is the cost that matters, and it is measured.** `lit` OCRs only pages with
  no text layer, so 120 generated pages cost a fraction of a second — but a
  *scanned* page costs **8.8 s**, so a 300-page scan is about 44 minutes against a
  300-second command ceiling: killed, with nothing to show. `--target-pages 1-40`
  bounds it (three scanned pages in 1.6 s), and `--no-ocr` on a scan **succeeds and
  returns 179 bytes** — a silent near-empty answer, which is the worse of the two
  failures. Both are in the briefing below, because this is exactly the request a
  user makes: "summarise this book".
- **No `build-essential` (+94 MB) and no `scikit-learn`/`scipy` (~200 MB).** Both
  are `uv pip install` away on a runtime that has a network. The cost of leaving
  them out is a first-time install; the cost of baking them in is paid by every
  host at every start-up.
- **`requests` beside `httpx`, and `tabulate` beside `pandas`**, at half a
  megabyte between them: a model writes `import requests` and `df.to_markdown()`
  from muscle memory, and neither is worth a failed script and a retry.
- **`tzdata` and `fonts-dejavu-core`** are in the apt layer because `python:slim`
  has neither, so `zoneinfo` raises and `PIL.ImageDraw.text` cannot load a font —
  both verified before and after.
- **`env_vars` rather than a habit.** `MPLBACKEND=Agg`, `PYTHONUTF8=1`,
  `PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1` are properties of the image;
  a run that has to remember them is a run that will not.

### The model is told all of this

A container is useless to an agent that does not know what is in it. Before
#1040 an agent asked for a chart would `import plotly`, and one handed a PDF
would write its own extractor beside the `lit` that reads it — each learning
otherwise by failing inside somebody's request.

**And it is told how to work, not only what is installed.** The instruction that
earns its place is the one nothing else can teach: *do not read a large file to
look through it*. Extract it once to a text file, `rg -n` for the places that
matter, `sed -n '400,460p'` to read one. A book is thousands of lines and an
answer needs tens of them, and a model that pulls the whole thing into its own
context spends the run's budget on pages nobody asked about. The same paragraph
carries the two OCR traps above, because a scanned book is where both of them
land at once.

So every run on a runtime this deployment ships has a paragraph appended to its
instructions: which runtime it got, the package list, the `lit` line, what
`soffice` converts, the one gap (no C compiler), and whether it has a network. It is
**composed from the catalogue**, not written beside it — `runtime_briefing` reads
the package list off the definition, so a package added to the file reaches the
prompt in the same edit that reaches the image. Only what cannot be derived is
prose, in the entry's `briefing` list.

Two consequences worth knowing. It is appended **per run**, the way a channel
binding's prompt is, because which runtime a run gets is resolved from the spec,
the connection and the host as the run starts — the published spec is left
alone. And an alias this deployment does not ship gets **no** paragraph: a host
started with an allowlist of its own is not one whose images we can honestly
describe, and a prompt that guesses is worse than a prompt that is silent.

### Changing it

```bash
$EDITOR backend/app/core/catalog/sandbox_runtimes.json
make sandbox-runtimes          # writes SANDBOXD_RUNTIMES into all three compose files
docker compose up -d sandboxd  # prewarm rebuilds what the list now names
```

An entry is one of two shapes, never both:

```json
{
  "alias": "workbench",
  "description": "What it is for - shown in the connection dialog",
  "base_image": "python:3.12-slim",
  "setup_commands": ["apt-get update && apt-get install -y --no-install-recommends git"],
  "packages": ["pillow"],
  "mem_limit": "2g",
  "needs_network": true
}
```

| Field | |
|---|---|
| `alias` | What a spec names. Lower case, `[a-z][a-z0-9-]*` |
| `description` | Shown in the connection dialog's `Default runtime`. Say what it is *for* |
| `image` | A ready-made image. Starts in the time a pull takes, and installs nothing |
| `base_image` | Built once on first use and cached after — the shape that can install |
| `setup_commands` | Shell at build time, before the packages: an apt layer, an installer |
| `packages` | `pip`, installed at build time. Needs a `base_image` |
| `env_vars` | Set in every container on this runtime — `MPLBACKEND`, `PYTHONUTF8` |
| `briefing` | Sentences the model is told that cannot be derived from the fields above |
| `mem_limit` | Docker's own syntax (`2g`). Absent, `SANDBOXD_MEM_LIMIT` applies |
| `needs_network` | Whether a **session** on it gets a network. A build always has one |

Four things the file will not let you get wrong, or that will bite if you skip
this section:

- **`image` and `base_image` are exclusive**, and a `packages` or
  `setup_commands` list on an `image` entry is refused at import. Accepted, it
  would be a runtime whose packages are in the catalogue, in the compose file, and
  not in the container.
- **The first entry is the default** for an agent whose spec names no runtime, so
  the order of the file is load-bearing.
- **`network_mode` is not inherited.** `SANDBOXD_NETWORK_MODE` is service-wide and
  every shipped compose file sets it to `none`, so an entry that installs anything
  at run time needs a network of its own. `needs_network` is that decision, made
  once where the packages are rather than remembered per compose file; missed, the
  failure is an agent whose `uv pip install` times out.
- **A malformed entry stops the deployment**, deliberately — the catalogue is
  validated at import rather than at first use, because a picker with a hole in it
  is discovered by a user.

### Why the value is also in the compose files

`SANDBOXD_RUNTIMES` is the **only** channel the service accepts runtimes on. A
compose file cannot call a command, so the value there is a generated copy, and
the only question worth answering is whether it can drift:
`backend/tests/test_sandbox_runtime_catalog.py` fails when one has, naming the
file and telling you to run `make sandbox-runtimes`.

Generated *into* a tracked file rather than read from a side file at start-up,
because `docker compose up` has to work without generating anything first — the
alternative is a deployment silently taking the library's own default allowlist.

And it is not a form in the product. `PUT /policy` changes ceilings and lifetimes
at run time and deliberately refuses the *membership* of this list, along with
`network_mode`, `oci_runtime`, `sandbox_uid`, `work_dir` and `persist_containers`:
naming an image is a decision about isolation, and the service token is held by an
application rather than by whoever runs the host. Changing the list is a restart.

### Two lists in the product, answering different questions

The **connection dialog's** `Default runtime` offers this catalogue — what the
compose files gave the service — populated before any host has been asked, and
marked once one has answered. The **agent Builder's** `Runtime` offers what the
service on that connection *actually* allows, read live from it, so an alias it
names is one the next tool call will accept. Where the two disagree the second is
right: a host can have been started with a different allowlist, and a deployment
that generated its own is exactly the case worth not dropping.

## When a build is paid for

`prewarm` is on, so the allowlist is pulled and built in the background **as the
service starts** rather than inside somebody's first request — a build is ten
seconds and upwards. Images are cached, so a host pays once.

What is left to wait for: the first session opened *during* a prewarm, and a host
whose image cache was cleared. `SANDBOXD_PERSIST_CONTAINERS: true` then removes
most of the rest — a closed session keeps its container, so the next session on
that workspace starts without a build and with whatever the agent installed last
time still installed.

## Isolation, plainly

What holds:

- the sandbox cannot see the Docker socket; only `sandboxd` can;
- no network at all unless the runtime asks for one, and only `workbench` does;
- 2 CPUs, 512 processes and a 64 MiB `tmpfs` at `/tmp` per sandbox, plus
  `SANDBOXD_EXECUTE_TIMEOUT` (300 s) on every command and
  `SANDBOXD_MAX_READ_BYTES` (8 MiB) on every read;
- `SANDBOXD_SANDBOX_UID: 10001` — a sandbox runs as an unprivileged user rather
  than as root, and every file an agent writes is owned by that uid on the host. It
  **has to be the service's own uid**: opening a session `chown`s the workspace to
  this user, and an unprivileged `sandboxd` can only do that for itself, so a
  different number fails at the first session rather than at start-up. It applies
  to a runtime this deployment *builds* — a ready-made image has no such account
  and no virtualenv, so an agent inside one could install nothing.

What remains, stated rather than implied:

1. **The service token is root-equivalent.** See above.
2. **Escaping the container is escaping to the host.** Ordinary `runc`;
   `oci_runtime` can name a sandboxed one (gVisor's `runsc`) where a deployment
   wants that trade.
3. **A runtime with a network can reach ports published on the host.**
   `docker-compose.yml` publishes Postgres and Redis for local development, with
   `postgres/postgres`; `docker-compose-prod.yml` publishes neither. So this is a
   laptop caveat rather than a production one — but it is the cost of giving
   `workbench` a network, and worth knowing before copying the local file to a
   shared host.

## What the file browser shows, and what it leaves out

`/workspaces` lists what an agent is keeping **for a person**, which is not the
same set as what is on the volume. Two prefixes are dropped from every listing a
person reads - the flat view, a workspace's own files, a conversation's panel, and
the file counts:

- `skills/` — a skill's body and its resources, written at the start of every run
  that has both skills and a workspace. They are needed there: a resource is a
  script the shell runs, and `collect_changes` diffs these files into a proposal
  somebody accepts. They were removed once because the listing was mostly them,
  which was the right complaint about the wrong thing (#1064).
- the spill directory — where a tool's overflowing output was written.

A count has to drop them too, or a workspace reporting four files where one is
visible is a count nobody can check.

**A file says who put it there.** `uploads/` is where an attachment lands, so a
path under it is a file a person attached and anything else is the agent's own
work — offered as a filter and said on the tile. It is the only signal available:
a host records no author and neither does the state document. Its limit follows
from that: an agent writing into `uploads/` itself is indistinguishable from a
person, and nothing stops it.

**Listing a container costs round trips, so two things are bounded.** The archive's
`ls` reads one directory, so the listing walks - depth-first bounded, and stopping
at 2,000 entries, because a host holding a `node_modules` must not turn one
workspace into ten thousand rows. And an image's thumbnail is a `read_bytes` for
that file: the suffix and the size are checked off the listing entry before
anything is fetched, and one request draws at most 24. Past that a tile keeps the
glyph. A *stored* workspace pays neither - its files and their bytes are a column
of the row the listing already read.

## How long anything survives

Files live on the host, at `{SANDBOXD_WORKSPACE_ROOT}/{session_id}/workspace` —
`/tmp/agenticos-sandbox-workspaces` locally, `/var/lib/agenticos/sandbox-workspaces`
on the dev server and in production. That bind mount is also what makes the
product's Files panel possible: reading a workspace never starts a container.

| | Setting | What happens |
|---|---|---|
| An idle session | `SANDBOXD_IDLE_TIMEOUT` 1800 s | The container is closed and reaped. **The files stay** |
| A stopped container | `SANDBOXD_CONTAINER_TTL` 86400 s | What the session installed — the build, the wheels, `node_modules` — is reclaimed. The workspace is untouched |
| The workspace directory | `SANDBOXD_WORKSPACE_TTL` **unset** | Kept **indefinitely** |

The last row is the library's default and it is deliberate — the notes and scripts
are the work, and an agent's user expects them next week. The consequence is that
disk use only grows: nothing sweeps a workspace whose conversation nobody will
open again. `/tmp` is cleared by a reboot on a laptop; `/var/lib` is not. A
deployment with a retention policy sets `SANDBOXD_WORKSPACE_TTL` to the number
that policy says, and the files older than it go.

Deleting a conversation purges its workspace through the product, so this is about
what nobody deletes rather than about what they do.
