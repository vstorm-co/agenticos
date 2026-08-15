# Context

Puts an organization's standing context into a run - a glossary, a brand voice,
an escalation matrix, the list of products the company sells. It is the database
form of the pattern `clock` is the smallest instance of: known facts put into
the run instead of made to be asked for. The reference it ports is the
`RepoContext` capability in `pydantic-ai-harness`.

The files themselves are org-scoped rows (`app/db/models/context.py`), managed
through `/api/v1/context` and bound to an agent by id (`AgentSpec.context_ids`).
This package is only the run-time half: given the files the runner resolved, it
decides how each reaches the model.

## Two modes, chosen per file

A context file carries a `mode`, and the capability branches on it:

- **`inject`** - the body is spliced into the agent's instructions verbatim, so
  the model simply knows it. It costs the tokens of the body on every run, which
  is the right trade for something short and always relevant.
- **`link`** - the body is left out of the prompt and reached through
  `read_context`. `list_context` shows the model what exists (name and one-line
  description), and it loads only what it decides is relevant. The right trade
  for something large or rarely needed.

The mode lives on the file, not on the binding, so the same file reads the same
way for every agent that uses it.

## Injected content is untrusted input

A file's body is written by a person and reaches the model verbatim, so injected
content is prompt surface. It is delimited with `<context-files>` tags and
preceded by a line telling the model to treat everything inside as information
rather than as instructions - the same discipline a code-review prompt uses on a
diff it did not write. Without it, a file that happened to contain "ignore your
previous instructions" would be read as a command.

## What it deliberately does not do

- **Binary files.** Content is text: an injected body becomes prompt and a linked
  body is returned to the model as a string, so a PDF would arrive as noise. A
  document to be searched belongs in a knowledge collection (RAG), which is
  retrieval, not standing context. `format` is a fencing hint (`md`, `txt`,
  `json`, `yaml`, `csv`), not a licence to store bytes.
- **Per-request resolution.** The files are read once when the run is prepared,
  so an edit made mid-conversation is picked up on the next run, not the next
  turn - the same as skills, and unlike `clock`, whose content genuinely changes
  every second.
- **Fetching its own files.** The runner resolves them from the database and
  hands them in; the capability never queries. The model chooses *what* to read,
  never *where* it lives.

## Contributes nothing when there is nothing to contribute

Bound with no files - or with only linked files and `expose_read_tool` off - the
builder returns `None` and the capability is not attached at all: no empty
preamble in the instructions, and no `read_context` tool that could only report
that there is nothing to read.

## Configuration

| Field | Default | What it is |
|---|---|---|
| `expose_read_tool` | `true` | Whether link-mode files are reachable through the read tool |
