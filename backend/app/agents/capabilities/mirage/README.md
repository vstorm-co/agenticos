# Mirage - a virtual terminal over the services an author mounts

`mirage` gives an agent a shell and the console's file tools over the services its
author chooses: a Google Drive, a GitHub repository, Notion, a Postgres database,
an SSH server, a mailbox. [Mirage](https://github.com/strukto-ai/mirage)
(strukto.ai, Apache-2.0, `mirage-ai` on PyPI) mounts each one as a folder and runs
the shell over it, reading every folder through its service's own API. An agent
then answers "which contracts mention Acme?" with a `grep` across a Drive folder,
without starting a container.

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

The library is the optional `mirage` extra, pinned to 0.0.8 in the extra and
test environment. It no longer needs the previous tree-sitter compiler step.
The registry imports no Mirage modules unless the capability is used.

RAM folders survive approval pauses in the run's serialized message metadata;
remote credentials and caches never enter this snapshot. A continuation consumes
its snapshot so a later conversation turn cannot resurrect old scratch files.
Each workspace has a 16 MiB cache and 16 MiB working-memory budget. Shell streams
are collected up to 64 KiB each, with a visible incomplete-result refusal at the
bound, and the command deadline covers collection as well as execution. Direct
`curl` and `wget` calls are disabled even when the author lists them explicitly;
network work belongs to mounted services or the platform’s web capabilities.

## The evaluation (2026-11-04, `mirage-ai` 0.0.8)

- **Maturity.** A preview, pinned exactly. The registry API provides: a registry of
  ~50 backends with typed configs, permission profiles, policies and `explain`,
  and a Pydantic AI workspace backend - which is what made the console tools and
  the per-folder approval possible without a parser of our own.
- **Not available here:** the S3 family (S3, R2, GCS, OCI, MinIO and other
  S3-compatible stores) needs `aioboto3`, which pins `boto3` below the 1.43 this
  project runs on; `disk` reads the server's own filesystem.
- **Isolation.** Mount modes, hidden paths and the command allowlist are enforced
  in-process by Mirage's dispatcher and shell. That is a policy boundary, not a
  security boundary against the process; the credential's scope is what bounds what
  a folder can reach.

Qdrant and Langfuse are compatible with the current dependency lock. Qdrant is
file-oriented here: its optional embedding callback and cloud inference switches
are hidden, so terminal commands cannot start unmetered model calls.

MongoDB and GridFS connect directly to one allowlisted `mongodb://` authority.
The platform forces `directConnection=true`; SRV and replica-set discovery are
not available because discovered hosts would bypass the exact-host allowlist.
Unlinked channel senders need approval for all terminal tools, including reads.
Organization-account consent rechecks the initiator’s current permissions before
exchanging the provider code.

PostgreSQL mounts require a nonempty password in the vault DSN; empty passwords and passwordless authentication are not supported. They do not fall back to `PGPASSWORD` or `.pgpass`. DSN parameters naming host credential or TLS files (`passfile`, `servicefile`, `sslkey`, `sslcert`, `sslrootcert`, `sslcrl`) are refused.

SSH is password-only through the vault, with an explicit username and pinned
public host key. The adapter disables API-host SSH config, agent authentication
and default private keys. It replaces only the connection setup of Mirage 0.0.8’s
SSH accessor; real SFTP and cancellation tests pin its protected lifecycle fields.


### Rechecked backends (2026-11-04)

- Box is available through its existing Client Credentials service-account flow.
  It requires a client ID, enterprise ID and vault client secret; developer tokens
  and rotating OAuth grants are rejected. No extra dependency is needed.
- LanceDB 0.41.0 and PyArrow 26.0.1 resolve with the current lock and have compatible
  wheels for the tested Python 3.15 environment. They are included only through
  the optional Mirage extra (and the test group). The downloaded macOS ARM64 wheels
  total about 101 MiB compressed; ordinary images do not include this extra.
- LanceDB accepts only `db://database-name`, a required vault API key and an
  explicit HTTPS `host_override` checked at publish and runtime. Local paths,
  object-store URIs and `storage_options` cannot inherit host credentials.
- A fresh resolver check still rejects `aioboto3>=15.5.0` with
  `boto3>=1.43.114`: the latest aioboto3 pins aiobotocore 2.25.1, whose boto3 extra
  requires `boto3>=1.40.46,<1.40.62`. No pins are overridden or downgraded.

Sources: [aioboto3 metadata](https://pypi.org/pypi/aioboto3/15.5.0/json),
[aiobotocore metadata](https://pypi.org/pypi/aiobotocore/2.25.1/json),
[LanceDB releases](https://pypi.org/project/lancedb/0.41.0/),
[Box CCG](https://github.com/box/developer.box.com/blob/main/content/guides/authentication/client-credentials/index.md).
