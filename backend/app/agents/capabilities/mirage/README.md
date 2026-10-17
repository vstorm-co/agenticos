# Mirage - a virtual terminal over mounted sources

`mirage` gives an agent `ls`, `cat`, `grep`, `find`, `head` and `wc` across its
knowledge bases, the files behind their sources and GitHub repositories, without
starting a container. [Mirage](https://github.com/strukto-ai/mirage)
(strukto.ai, Apache-2.0, `mirage-ai` on PyPI) mounts each source under one tree
and runs a virtualized shell over it, reading files through the source's own API.

## What it mounts

- **Knowledge bases** (`knowledge`, on by default), read-only, at
  `/knowledge/<base>/`: each indexed document of a bound base as its parsed
  text, read back from the vector store with the splitter's overlap kept once.
- **Their sources** (`sources`), read-only, at `/sources/<source>/`: the files
  of each active S3, Google Drive, SharePoint or Git sync source of those bases,
  this organization's only, listed and read through the platform's own connector
  with the credential the source syncs with. A website source is left out; its
  pages are already documents. A file over 20 MB is refused.
- **GitHub repositories** (`github`), read-only, at `/github/<owner>/<name>/`, up
  to five, optionally at a branch (`owner/name@branch`).
- **A scratch folder** at `/scratch/`, writable, in memory, empty each run.

Knowledge bases and sources are Mirage `GenericResource`s built in `_tree.py`
from a flat listing and a reader that the runner resolves
(`app/services/mirage_mounts.py`) - a capability must not read the database or
the vault itself. What a failing source raised is logged, never shown: the shell
prints an exception's text, and a connector's can carry a bucket policy or a
signed URL, so the model reads only that the folder could not be listed or read.

The GitHub token is the binding's secret: a `git_token` from the vault, sealed for
`github.com`, asked for only when `github` is on. It is required even for public
repositories then, because Mirage sends a token with every API request and GitHub
answers 401 to an empty one. A token sealed for another host is refused at build
time rather than sent to GitHub.

## The policy

`allowed_commands` and `hidden_paths` are compiled into Mirage's own
`SessionProfile` (`commands.allow`, `paths.hide`), so the shell that parses a line
enforces them - through pipes, `$(...)` and `find -delete` - rather than a second
parser here that could read the line differently. An empty `allowed_commands` is
Mirage's unstated `allow`: every command.

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
- **A quirk.** In 0.0.6 one `grep` line naming folders on two different mounts
  searches only the first mount's operands, without an error. The instructions
  tell the model to grep from `/` or once per folder.
- **Dependencies.** Five new distributions (`mirage-ai`, `dulwich`, `jq`,
  `tree-sitter`, `tree-sitter-bash`), all Apache-2.0, MIT or BSD; `dulwich` is
  Apache-2.0 OR GPL-2.0-or-later and taken under Apache-2.0.

## Not yet

- **Mirage's own S3 and Drive resources.** Its `s3` extra needs `aioboto3`, whose
  `botocore` range does not resolve beside the `boto3` the backend pins, and its
  Drive resource takes a person's OAuth account. Both stores are mounted through
  the platform's sync connectors instead, which also reuses the credential an
  organization already validated for the source.
- **Usage of a model Mirage calls.** None of the mounted sources call a model, so
  there is nothing to meter yet.
