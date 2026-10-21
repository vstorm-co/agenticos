# Mirage - a virtual terminal over the services an author mounts

`mirage` gives an agent a shell and the console's file tools over the services its
author chooses: a Google Drive, a GitHub repository, Notion, a Postgres database,
an SSH server, a mailbox. [Mirage](https://github.com/strukto-ai/mirage)
(strukto.ai, Apache-2.0, `mirage-ai` on PyPI) mounts each one as a folder and runs
the shell over it, reading every folder through its service's own API. An agent
then answers "which contracts mention Acme?" with a `grep` across a Drive folder,
in seconds and with no container.

## What a spec says

Each **mount** is a folder (`/drive/`), a backend (`gdrive`), read or write,
whether a person approves each write, the backend's own options (a repository, a
folder id, a host), and its credential:

- **secrets** - a vault secret per credential field the backend has (`token`,
  `api_key`, `dsn`...), each an `api_key` secret holding the value;
- **an Entra app** - for OneDrive and SharePoint, an `entra_app` secret under
  `app`, which the runner signs in as for a Graph token per run;
- **a connected account** - for the Google services: the organization's, named
  by id, or each person's own, found when they talk to the agent. A person with
  several gets a folder per account under the mount.

The spec never holds a credential's value, an endpoint override (`base_url`,
`api_base`, `endpoint` are not offered) or a path on the API host (`ssh`'s
`identity_file` and `known_hosts` are not either). A host an author types - an SSH
server, a DSN's, an IMAP server's - must be on `MIRAGE_ALLOWED_HOSTS`, checked at
publish for a typed option and again by the runner, which can read the ones inside
a secret.

`_backends.py` builds the catalog the Builder offers from Mirage's own registry,
so a backend Mirage adds appears without a form being written - and lists the ones
this deployment cannot run with the reason, rather than leaving them out.

## The tools

`pydantic-ai-backend`'s console - `ls`, `read_file`, `glob`, `grep`, `write_file`,
`edit_file`, `execute` - the same seven `sandbox` offers, with the same text,
prefixed `mirage_`. They are **pinned** to the terminal rather than reaching
`ctx.workspace`, which is the run's one workspace and belongs to `sandbox` when an
agent has both: each call gets a context whose workspace is the terminal. An agent
can keep scratch files in its sandbox and read the company's Drive in one turn.

## Approval is per folder, not per tool

`mirage_execute ls` and `mirage_execute rm /drive/q3.pdf` are one tool, so gating a
tool asks about both. A writable folder marked "approve each write" is asked about
instead, by what a call would write (`_policy.py`):

- `mirage_write_file` and `mirage_edit_file` write their `path`;
- for `mirage_execute`, Mirage's `explain` dry-runs the line through the same
  policies it will meet, and `WriteApproval` answers `Ask` for a write into a
  gated folder - a redirect, `cp`, `tee`, `rm` alike.

The question goes to the platform's gate under the running call's id, before the
call runs: granted runs it, rejected returns the gate's refusal, nobody-yet parks
the run with `ApprovalRequired`. Mirage's own `on_ask` is a backstop, not the
mechanism - Mirage catches an exception raised there and fails the line, so a
question cannot be parked from inside it. It allows a gated write only during an
approved call and refuses one any dry run missed, such as `echo x > $TARGET`.

No tool is `side_effecting`. A binding that wants one gated anyway still sets a
`tool_approval` override.

## Installation

The library is the optional `mirage` extra. `tree-sitter`, which Mirage parses
shell lines with, has no Python 3.15 wheel and compiles, so a build that wants the
terminal pays for a compiler (`EXTRAS="--extra mirage"`) and one that does not is
unchanged. This package imports none of Mirage at module level; `_capability.py`
and `_policy.py` do, and are imported only when an agent bound to the terminal is
built. The suite installs the same pin through the `dev` group.

## The evaluation (2026-10-22, `mirage-ai` 0.0.7)

- **Maturity.** A preview, pinned exactly. 0.0.7 reworked the API: a registry of
  ~50 backends with typed configs, permission profiles, policies and `explain`,
  and a Pydantic AI workspace backend - which is what made the console tools and
  the per-folder approval possible without a parser of our own.
- **Not available here:** the S3 family (S3, R2, GCS, OCI, MinIO and other
  S3-compatible stores) needs `aioboto3`, which pins `boto3` below the 1.43 this
  project runs on; `qdrant`'s client has no 3.15 build; `lancedb` brings `pyarrow`;
  `langfuse` would move the OpenTelemetry the platform traces with; `box` rotates
  its refresh token on every use, so a stored one stops working; `disk` reads the
  server's own filesystem.
- **Isolation.** Mount modes, hidden paths and the command allowlist are enforced
  in-process by Mirage's dispatcher and shell. That is a policy boundary, not a
  security boundary against the process; the credential's scope is what bounds what
  a folder can reach.
