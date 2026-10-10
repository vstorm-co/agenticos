---
title: "Build an LLM wiki the agent maintains"
description: "Give an agent a workspace that survives across conversations and a schema file, and let it turn raw notes into a small, cross-linked Markdown wiki."
---

# Build an LLM wiki the agent maintains

Andrej Karpathy described this pattern in April 2026: keep raw sources
untouched in one place, have an agent compile them into a small, interlinked
Markdown wiki in another, and write down the schema so any later session can
check itself against it rather than guessing the layout again. This builds
that on a workspace that outlives a single conversation, with two synthetic
sources ingested a session apart. This is a procedure to run, with one
recorded run as a reference — the two ingest conversations below were run in
full; the question and the lint step were not reached in that run, and are
marked as such.

## What you need

- A [running installation](../install.md) with a model profile and a
  registered [sandbox connection](../sandbox.md) offering the `workbench`
  runtime.
- No other capability. The wiki lives entirely in the agent's workspace.

## Prepare the input

Two short, unrelated-looking notes that turn out to share a fact, so the
wiki has a reason to cross-link them.

Source one, pasted in the first conversation:

```text
Meeting notes, 3 March. The team adopts a weekly on-call rotation starting
Monday. Alice is on-call first, then Bob, then Carol, rotating every Monday
at 9am. Escalation rule: if the on-call person does not respond within 15
minutes, page the backup, who is always the previous week's on-call person.
```

Source two, pasted in a second, separate conversation:

```text
Incident report, 11 March. A database outage occurred on Tuesday. Alice was
on-call and responded within 5 minutes; the backup escalation was not
needed. Root cause: a migration script left a lock unreleased. Fix: the
migration now acquires the lock with a timeout.
```

The reference fact a wiki page has to carry across both notes: Alice was
on-call for the outage because of the rotation set on 3 March, and the
backup rule from that same rotation was not triggered.

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, enable **Sandbox**. Choose **Container**, select
   your sandbox connection and the `workbench` runtime.
3. Set **session scope to `user`**, not the `conversation` default. A
   conversation-scoped workspace starts empty on the next chat, which is
   exactly the "wiki forgets everything" failure this page is checking for;
   an agent-scoped one is shared by everyone in the organization who talks
   to this agent, which is the wrong sharing model for one person's wiki.
   `user` keeps one workspace for the person across every conversation and
   surface they reach the agent on, and nobody else's. See
   [Sandbox](../reference/capabilities.md#files-shell) for what each
   scope shares.
4. Set a budget and a step limit for the trial.
5. Set the instructions below, then **Publish**.

```text
You maintain a small personal LLM wiki in your workspace: raw sources
compiled into a cross-linked Markdown wiki, following this schema.

Layout:
raw/<slug>.md - one file per ingested source, saved verbatim, append-only.
Never edit a raw file once written.
wiki/index.md - one line per wiki page, each a Markdown link to it.
wiki/<topic>.md - one page per topic, written in your own words from the raw
sources. Link related pages with a relative Markdown link.
schema.md - this layout, written once on your first turn if it does not
exist, so any later session can check itself against it.

When asked to ingest a source: read schema.md first, writing it if it is
missing; list wiki/ so you know what exists; save the source verbatim to
raw/<slug>.md; update an existing wiki page if the source is about it, or
create a new one only for a genuinely new topic; cross-link pages that refer
to each other; update wiki/index.md; report which files you touched.

When asked a question, read the relevant wiki page(s) - not the raw sources,
unless a page is missing something the question needs - and answer citing
the page you used by name.

When asked to lint the wiki: list every file, read wiki/index.md and every
page it links to, then report broken links, orphan pages nothing links to,
and any two pages that state different facts about the same thing. Do not
fix anything unless asked; only report.
```

The schema lives in the instructions here because it is short. A schema that
grows past a paragraph or two is a better fit for a [context file](../context.md)
in `link` mode, read once and shared across every agent that maintains a wiki
this way, rather than pasted into each one's instructions.

## Run it

In a first, fresh conversation:

```text
Ingest this source: [paste source one]
```

Start a **second, new conversation** with the same agent — not a reply in
the first one — and ask it to ingest the second source, then ask the
question:

```text
Ingest this source: [paste source two]
```

```text
Who was on-call during the outage, and what is the backup escalation rule?
```

In a third turn, or a third conversation, ask for the check the pattern is
built around:

```text
Lint the wiki.
```

## Check the result

| Check | Reference |
| --- | --- |
| `schema.md` after the first conversation | Exists, matches the layout in the instructions |
| Workspace at the start of the second conversation | Already holds `schema.md`, `raw/`, `wiki/` from the first — nothing is re-created |
| Wiki page(s) after both sources | Mentions Alice, the rotation order, and the outage; the two topics link to each other rather than sitting as two disconnected pages |
| Answer to the question | Names Alice, cites the wiki page(s), and states the backup rule was not triggered |
| Lint report | Names any broken link or orphan page truthfully — including "none found" — rather than a generic "looks good" |
| A third conversation asking a question with nothing ingested yet | Reads the existing wiki and still answers, because the workspace is the person's, not the conversation's |

Read the actual files through the conversation's file panel, not only the
reply. A model that describes updating a cross-link and one that actually
wrote it look the same in prose.

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter, `workbench` runtime,
    `session_scope: user`. The first conversation found no `schema.md` and no
    `wiki/`, wrote both from the instructions' layout, saved the on-call note
    to `raw/meeting-notes-2024-03-03.md`, and created `wiki/on-call-rotation.md`
    and `wiki/index.md` — no `execute` call, so no approval was needed. Cost:
    0.1022 USD.

    A second, separate conversation with the same agent opened by reading
    `schema.md` and listing `wiki/`, and found both already there — the
    workspace had persisted. It saved the incident report to
    `raw/incident-report-11-march.md`, created `wiki/database-incidents.md`
    naming Alice, the 5-minute response and the root cause, then used
    `edit_file` on `wiki/on-call-rotation.md` to add an "Incidents" section
    linking to the new page, and updated `wiki/index.md` to list both pages —
    a genuine two-way cross-link, not two pages sitting side by side. Cost:
    0.1250 USD.

    An infrastructure outage unrelated to the agent or the sandbox stopped the
    trial here. The question ("Who was on-call during the outage...") and the
    lint step were not run, so the corresponding rows in the table above are
    the expected reference, not an observed result. What is confirmed is the
    part this page exists to check: the workspace survived a wholly separate
    conversation and the two topics linked to each other rather than
    duplicating content.

## When it goes wrong

- **The second conversation starts from an empty workspace.** The scope is
  `conversation` or `agent` binding to a different default connection than
  the first run used, or the connection or backend changed between the two —
  any of those starts a fresh workspace rather than reattaching to the old
  one.
- **Two pages repeat each other instead of cross-linking.** The model did not
  read `wiki/index.md` before writing. Tighten the instructions to require
  listing the wiki first, every time.
- **The lint report always says everything is fine.** Ask it to lint a wiki
  you know has a problem — rename a linked file first — to check the report
  is reading the files rather than assuming.
- **`schema.md` gets rewritten every conversation.** The instructions say to
  write it only if missing; if the model still rewrites it, tell it
  explicitly to read before writing anything.
- **A colleague can see notes you thought were private.** Check the session
  scope. `agent` shares one workspace with everyone who talks to this agent,
  and the Builder warns at the field for exactly this reason.

## Record the trial

Keep both raw sources, the exact prompts, the agent version, and the
workspace's file listing after each conversation — not just the replies. A
person still judges whether a cross-link is actually useful or just present,
and whether the lint report caught something real.

## Wiki or knowledge search?

They answer different needs. [Knowledge search](../reference/capabilities.md#knowledge-search)
retrieves passages from documents nobody rewrites — a signed contract, a
policy PDF — and cites the source chunk. This pattern is for material that
starts messy and small and is worth an agent's time to *compile*: notes,
transcripts, half-finished write-ups that benefit from being turned into a
small number of maintained pages instead of a growing pile of source files.
Once the compiled wiki itself becomes too large to inject or to read whole,
searching it like any other collection is the natural next step rather than
a workspace file.

## Next steps

Try ingesting a source that contradicts an earlier one on purpose, and check
that the lint step names both pages rather than silently picking a side. For
a wiki several people should be able to read and extend, weigh the `agent`
session scope against giving each contributor their own agent bound to a
shared [context file](../context.md) instead.
