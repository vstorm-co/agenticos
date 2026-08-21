# Sandboxes, runtimes and workspaces

Nine things asked in one sitting, on the Docker (`sandboxd`) backend and the
surfaces around it. `daytona` and `state` are out of scope except where a fix
touches both.

Everything under **Verified** was checked against the running deployment or the
source, and says how. Everything under **Decision** is a choice this plan makes
and can be argued with. The task lists are what ships.

---

## 1. Can `sandboxd` run on another host?

**Asked.** It is defined in `docker-compose.yml` today — could it live on another
server and be connected to?

**Verified.** Yes, and that is the shape the product already has. A sandbox
connection is a `base_url` plus a credential in the vault
(`app/services/sandbox_connection.py`), and nothing in it assumes a local
address: `POST /api/v1/sandbox-connections/probe` asks whatever address it is
given whether it answers and what it allows. The compose service is one
deployment of `ghcr.io/vstorm-co/sandboxd:0.2` and sits behind the `sandbox`
profile.

What a remote host needs, and what the compose file happens to give it locally:

- the Docker socket, because the service starts containers (`/var/run/docker.sock`);
- `SANDBOXD_WORKSPACE_ROOT` on a real disk, mounted at the same path on both
  sides — the daemon resolves the bind mount on the *host*, so a named volume or
  a path that exists only inside the service's container is refused;
- `SANDBOXD_TOKEN`, which is root-equivalent on that host: a session runs
  commands there.

**Decision.** Nothing to build. This is a documentation gap: `docs/sandboxes.md`
explains the local service and never says the remote case is the same three
variables plus TLS in front. Write it.

- [x] Document running `sandboxd` on a separate host, with the three
      requirements above and the one thing that differs (the address is not
      `http://sandboxd:8080`, so it needs TLS and a token nobody shares).

---

## 2. What is `Default runtime` in *Add sandbox connection*, and why does the
Builder offer three?

**Asked.** The connection dialog offers fifteen runtimes; the agent's *Files &
shell* capability offers `default` plus `coding`, `node`, `python`. Why?

**Verified.** Two different lists, both correct, neither wrong on its own:

| Where | Source | What it is |
|---|---|---|
| Connection dialog | `BUILTIN_RUNTIMES` in the sandbox library, via `SandboxConnectionService.runtime_catalog()` | Fifteen image *recipes* the library ships |
| Agent Builder | `GET /sandbox-connections/{id}/policy`, proxied from the service | The aliases **this service actually allows** |

The Builder's three are `DEFAULT_RUNTIMES` in
`pydantic_ai_backends.remote.server` — `coding`, `python`, `node` — which is what
a service allows when its operator names nothing, and this deployment names
nothing. The `1g` beside each is the service-wide `mem_limit` default.

`Default runtime` on a connection is the fallback for an agent whose spec names
none. The dialog offers the library catalog before anything is probed
deliberately (`runtime-field.tsx` says why: a select that fills in only after a
button is a select nobody finds), and marks the aliases the service did not name
**once `Test` has been pressed**.

**Decision.** The design is sound and the deployment is the problem: twelve of
the fifteen offered aliases cannot run here, and nothing says so until somebody
presses a button. Two changes, neither of which touches the reasoning above:

- make the deployment allow a useful set (topic 3), so the offer and reality
  agree;
- probe automatically once the form holds an address and a credential, so the
  marks appear without a deliberate press.

- [x] Probe on the address/credential pair being complete, debounced, without
      removing the explicit `Test` button.
- [x] Say in the dialog, before any probe, that the marks come from asking the
      host — the current copy says nothing has been checked and not what would
      check it.
- [x] `docs/sandboxes.md`: the two lists, in a table like the one above.

---

## 3. Where are runtimes defined, and can a user add one?

**Asked.** Somewhere easy, so an agent gets python, javascript, LiteParse and so
on without a code change.

**Verified.** On the **service**, through `SANDBOXD_RUNTIMES`:

```
SANDBOXD_RUNTIMES=python=python:3.12-slim,data=@python-datascience;mem_limit=4g
```

`alias=image` for a ready-made image, `alias=@name` for one of the library's
fifteen recipes (built on first use, cached after), and `;field=value` modifiers
naming `SandboxRuntime`'s own fields — `mem_limit`, `cpus`, `network_mode`,
`pids_limit`. JSON is accepted for anything the compact form cannot say.

The library also ships `SUGGESTED_RUNTIMES`: eleven entries with ceilings already
chosen (`coding`, `polyglot`, `python`, `python-analytics`, `python-datascience`,
`python-documents`, `python-scraping`, `node`, `node-typescript`, `go`, `rust`).
Opt-in, because a default that raised ceilings would size somebody's host for
them.

**And a UI for it is refused upstream, on purpose.** `PUT /policy` changes
ceilings and lifetimes without a restart, and `wire.PolicyUpdate` deliberately
excludes `runtimes` membership, `network_mode`, `oci_runtime`, `sandbox_uid`,
`work_dir` and `persist_containers` — "adding an alias means naming an image",
which is an isolation decision, and the service token is held by an application
in a multi-tenant deployment rather than by the person who runs the host. That
reasoning is right and this plan does not argue with it.

**Decision.** Give the deployment a real allowlist rather than giving the product
a form that cannot be safe. Two of the asks land here directly: `python` and
`javascript` are `@python-*` and `@node-*` recipes; LiteParse is a pip package,
so it is a runtime whose recipe the library ships or a `packages` list in the
allowlist.

One trap found while reading: `SANDBOXD_NETWORK_MODE: none` is service-wide in
this compose, and `coding` needs the network for the reason it exists — an agent
installs what the project declares. `DEFAULT_RUNTIMES["coding"]` carries
`network_mode="bridge"` itself, but an allowlist written by hand does not inherit
that, so every entry that installs anything needs `;network_mode=bridge`
explicitly.

- [x] Ship an allowlist in `docker-compose.yml`: `coding` (bridge), `python`,
      `node`, `documents` (`@python-documents`), `data` (`@python-analytics`),
      `polyglot` (bridge). Ceilings per entry rather than one global number.
- [x] The same for `docker-compose-dev.yml` and `docker-compose-prod.yml`, where
      the ceilings differ.
- [x] A LiteParse runtime — decide between a `@python-documents` entry with
      `packages` and a new recipe in the library. If the library, that is a
      `pydantic-ai-backend` release.
- [x] `docs/sandboxes.md`: the syntax, the suggested set, and the
      `network_mode` trap.
- [x] `docs/configuration.md`: the variables this deployment sets and why.

---

## 4. `/workspaces` is ugly, and the file reader should look like `/skills`

**Asked.** Improve the table and the *All files* tab; the reader should be the
`/skills` shape — a tree beside a preview — as a modal or a page for one
workspace.

**Verified.** `WorkspaceBrowser` (379 lines) is a `DataTable` of workspaces plus
an *All files* tab that flattens every file of every workspace into one list, and
opening one mounts `FileViewer` — the shared dialog from `components/files`,
which has no tree. The skills editor is a two-pane layout: a file list on the
left, a preview or source on the right.

**Decision.** A workspace detail view in the skills shape, reachable from a row,
with the flat *All files* tab kept for the question it answers ("where is that
file, in whichever workspace"). `FileViewer` stays what it is — one file, from
anywhere — and the tree is the new part.

- [x] A workspace detail surface: a path tree on the left, `FileContent` on the
      right, the workspace's own facts in the header (backend, owner, bytes, the
      conversation behind it).
- [x] Fold real folders out of the flat paths — the browser has `path` strings
      today, so the tree is derived, not fetched.
- [~] Tidy the listing: the columns that earn their width, an access label, a
      link to the conversation, and the empty and failed states distinguished.
- [x] A tour stop and a `CreationFlow` entry if the surface is new (`tour.ts`,
      `flows.ts`, `detail-targets.ts` for a detail view with no route).

---

## 5. Uploaded files do not display, PDF included

**Asked.** The viewer is blank; the console says the CSP blocked
`blob:http://localhost:3000/…` against `default-src 'self'`.

**Verified.** `frontend/next.config.ts` has no `frame-src`, so it falls back to
`default-src 'self'` — and `file-render.tsx` renders a PDF in an `<iframe>` whose
`src` is a blob URL made in the browser. `img-src` already allows `blob:`, which
is why images work and PDFs do not.

**Decision.** One directive. `frame-src 'self' blob:` — not `data:`, which is the
one that lets an attacker's document be framed as same-origin, and not `*`.

- [x] `frame-src 'self' blob:` in the CSP.
- [x] A test on the header, because a directive nobody asserts is a directive the
      next edit drops.
- [x] Check the other viewers against the same list — HTML preview is an iframe
      too.

---

## 6. What is `/sandboxes?tab=running`, and when is a session open?

**Asked.** What should it show, and when is a session open or not?

**Verified.** It lists the sessions the *service* holds, refetched every ten
seconds, and it exists as its own tab because a live table under a table of
unknown height was unreadable (#140). A session is one workspace on one host,
and the states are the library's:

- **running** — the container exists and is resident. Opened on an agent's first
  tool call in a conversation.
- **hibernated** — the row exists, the container does not. A session idle past
  `evict_idle_after` is hibernated to free a slot, and its next request wakes it;
  this needs `workspace_root`, or waking it would open an empty workspace.
- gone — past `idle_timeout` (1800s here) the session is closed and reaped.
  `SANDBOXD_PERSIST_CONTAINERS=true` keeps the *container* alive across that so a
  restart is not a rebuild; `container_ttl` bounds how long a stopped one is kept.

**Decision.** Nothing is wrong here, and nothing on the screen says any of it.
Documentation, plus the two words the table is missing.

- [x] `docs/sandboxes.md`: the three states, what opens a session and what ends
      one, and which variable moves each boundary.
- [x] The tab explains itself in one line, and a hibernated row says what
      hibernated means rather than showing a state name.

---

## 7. What do the four compose values mean?

**Asked.** `SANDBOXD_PERSIST_CONTAINERS`, `SANDBOXD_MAX_SESSIONS_PER_TENANT`,
`SANDBOXD_NETWORK_MODE`, `SANDBOXD_UI_ENABLED`.

**Verified**, from `SandboxdConfig` and `config_from_env` (every field is
`SANDBOXD_` plus its name, no renaming):

| Variable | Here | What it decides |
|---|---|---|
| `PERSIST_CONTAINERS` | `true` | A closed session's container is kept rather than removed, so the next session on that workspace starts without a build. Costs disk and a stopped container per workspace; `CONTAINER_TTL` bounds it. |
| `MAX_SESSIONS_PER_TENANT` | `5` | One organization cannot take the whole pool. `MAX_SESSIONS` (20) is the pool. |
| `NETWORK_MODE` | `none` | The service-wide default for a sandbox's network. `none` is no network at all; a runtime may name `bridge` for itself, and `coding` does. |
| `UI_ENABLED` | `0` | The service's own dashboard, which asks a human to paste a root-equivalent token into a browser. Off because AgenticOS proxies the same data behind its own authorization. |

- [x] `docs/configuration.md` or `docs/sandboxes.md`: this table, plus
      `WORKSPACE_ROOT` and `IDLE_TIMEOUT`, which matter more than three of these
      four and are not mentioned anywhere.

---

## 8. Where is the workspace's 1 GB set?

**Asked.** `/chat` says `workspace 1% full` — where does that come from?

**Verified.** It depends on the backend, and the label does not say which:

- **container** — the percent is the sandbox's **resident memory** against the
  runtime's `mem_limit` (`1g` here, the service default). Sampled per session,
  `usage_report.SandboxUsage`.
- **stored (`state`)** — bytes in a JSONB column against
  `SANDBOX_STATE_MAX_BYTES`, whose default is **4 MiB**, not 1 GB.

So the 1 GB is a *memory* ceiling from the sandbox connection, set on the service
by `SANDBOXD_MEM_LIMIT` or per runtime in the allowlist. The tooltip says "in the
container"; the visible words say `workspace 1% full`, which reads as disk.

**Decision.** The number is right and the sentence is wrong. Say memory when it
is memory.

- [x] Distinguish the two in the usage strip's copy: memory for a container,
      stored bytes for a stored workspace.
- [x] Name where each ceiling is set, in `docs/configuration.md`.

---

## 9. The agent runs `ls` and the workspace is empty

**Asked.** A PDF is attached, the agent summarises it, then `ls` answers
`Directory '.' is empty or does not exist`.

**Verified, and this is a real bug.** `UPLOAD_DIR = "/uploads"` in
`app/services/attachments.py` is an **absolute** path, and the sandbox resolves
an absolute path as absolute. Probed against the running service:

```
write /uploads/probe.txt   -> {"path": "/uploads/probe.txt"}
write uploads/probe2.txt   -> {"path": "/workspace/uploads/probe2.txt"}
write probe3.txt           -> {"path": "/workspace/probe3.txt"}
```

and on the host, under `SANDBOXD_WORKSPACE_ROOT`:

```
s-7e13092d805f4ffc/workspace/probe3.txt
s-7e13092d805f4ffc/workspace/uploads/probe2.txt
```

`/uploads/probe.txt` is **nowhere on the host**. Three consequences, all
observed:

1. `ls` in the shell's working directory (`/workspace`) does not see it — the
   screenshot.
2. The workspace browser reads the host directory, which never sees it, so an
   attachment cannot be listed or opened from `/workspaces` either.
3. It lives in the container's write layer, so it dies with the container while
   everything in `/workspace` survives.

Every workspace on this host is empty on disk. The agent summarised the PDF from
the head sample in the prompt, not from the file.

**Decision.** Uploads go **inside** the work directory: `uploads/` relative, so
the service resolves it under `work_dir` whatever that is configured to be.
Absolute paths stay legal for anything that means them.

- [x] `UPLOAD_DIR` relative, and `workspace_path` returning a relative path.
- [x] Check every reader of that path: the reference given to the model, the
      workspace browser's addressing, `_write_extracted_text`, and the tests that
      assert `/uploads/`.
- [x] A test that an attachment lands where a shell's `ls` finds it — the
      assertion the current suite cannot make, because it mocks the backend.
- [ ] Say in the capability's prompt where attachments are, so a model that
      starts with `ls` looks in the right place.

---

## Out of scope, deliberately

- `daytona` and `state` backends, except `state` where `workspace_path` is shared.
- A UI for defining runtimes — refused upstream for a reason this plan agrees
  with (topic 3). If it is wanted anyway, it is a library change first: a
  curated image allowlist the service accepts over the wire, not free text.
- Anything about `/chat`'s attachment upload path itself, which works.

---

## Where this landed

Everything above is in one branch, `feat/sandbox-runtimes-and-workspaces`, with
the reasoning per part in the pull request's comments rather than in one wall of
commit messages.

Verified end to end against the running deployment after the image was pulled:

```
allowed: coding(1g,bridge) data(2g,none) documents(2g,none)
         node(1g,none) polyglot(1g,bridge) python(1g,none)
default: coding | work_dir: /workspace
write uploads/proof.txt -> /workspace/uploads/proof.txt
glob('**/*')            -> ['uploads/proof.txt']
```

and on the host: `s-…/workspace/uploads/proof.txt`, holding what was written. The
same glob answered 2540 paths of `/proc` and `/usr` before.

Two things deliberately left, both said out loud rather than quietly dropped:

- **`- [~]` on the listing table.** Its columns already answer real questions and
  the thing that made the page feel poor was the reader. A file count is the one
  column worth adding and cannot be added honestly - `WorkspaceSummary` carries
  none, and a container's would cost a round trip per row, which browsing never
  does.
- **The capability's prompt still does not say where attachments are.** With
  `uploads/` inside the work directory an agent's own `ls` now finds them, which
  is the failure that started this; naming the directory in the prompt is a
  separate change to what every agent is told, and belongs in its own diff.
