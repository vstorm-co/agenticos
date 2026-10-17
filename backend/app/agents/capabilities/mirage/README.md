# Mirage - a virtual terminal over mounted sources

`mirage` gives an agent `ls`, `cat`, `grep`, `find`, `head` and `wc` across GitHub
repositories, without starting a container. [Mirage](https://github.com/strukto-ai/mirage)
(strukto.ai, Apache-2.0, `mirage-ai` on PyPI) mounts each source under one tree
and runs a virtualized shell over it, reading files through the source's own API.

## What it mounts

- **GitHub repositories**, read-only, at `/github/<owner>/<name>/`, up to five,
  optionally at a branch (`owner/name@branch`).
- **A scratch folder** at `/scratch/`, writable, in memory, empty each run.

The GitHub token is the binding's secret: a `git_token` from the vault, sealed for
`github.com`. It is required even for public repositories, because Mirage sends a
token with every API request and GitHub answers 401 to an empty one. A token
sealed for another host is refused at build time rather than sent to GitHub.

## Two tools, one shell

`mirage_explore` runs a command in a view where every mount is read-only, so a
write fails inside Mirage with "Read-only file system" whatever the command says.
It needs no approval. `mirage_run` is the same shell over the view where the
scratch folder is writable; it is `side_effecting`, so **Always ask** gates it.
The two views share the scratch resource, so what `mirage_run` wrote is readable
from `mirage_explore`. Two tools rather than a `write` argument because the
approval gate keys on the tool, and an argument is something the model chooses.

A repository is never writable: Mirage reads it through GitHub's API and has no
way to write one back, and a write there fails with "Operation not supported".

Each command is stopped after `timeout_seconds`, and its output is cut at
`max_output_chars` with a note saying so. The workspaces are built on the first
command of a run and closed when the run ends; nothing is fetched until a
command needs a repository's tree.

## Why it exists beside `sandbox`

`sandbox` is a container: real processes, any tool, and a host to run it on.
Most of what an agent does with a repository is read it, and a container for
`grep` is a minute of startup and a host's capacity. Mirage answers the same
`ls` and `grep` from the API, so an agent can read across several repositories
in seconds. It cannot run code; use `sandbox` or the coding agent for that.

## The evaluation (2026-10-17)

- **Maturity.** 0.0.6, marked preview, pinned exactly in `pyproject.toml`. The
  shell, the GitHub source and the mount modes behaved as documented in the tests
  and against real repositories.
- **The Pydantic AI adapter is not used.** `mirage.agents.pydantic_ai` in 0.0.6
  imports `SandboxProtocol`, which the current `pydantic-ai-backend` no longer
  has, so it does not import. The capability calls `Workspace.execute` itself,
  which also keeps the tool text, the limits and the approval split ours.
- **Isolation.** Mirage enforces mount modes in-process: the read-only view
  refuses writes before any source sees them. It is not a security boundary
  against the process itself, which is why the credential is scoped by the
  vault's host check rather than trusted to the shell.
- **Dependencies.** Five new distributions (`mirage-ai`, `dulwich`, `jq`,
  `tree-sitter`, `tree-sitter-bash`), all Apache-2.0, MIT or BSD; `dulwich` is
  Apache-2.0 OR GPL-2.0-or-later and taken under Apache-2.0.

## Not yet

- **S3.** Mirage's `s3` extra needs `aioboto3`, whose `botocore` range does not
  resolve beside the `boto3` the backend already pins.
- **Google Drive and knowledge bases as mounts.** Drive needs a person's OAuth
  account rather than an organization key; a knowledge base would need a Mirage
  source of our own over the platform's documents.
- **Usage of a model Mirage calls.** None of the mounted sources call a model, so
  there is nothing to meter yet.
