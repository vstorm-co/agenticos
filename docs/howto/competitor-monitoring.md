---
title: "Watch web pages for changes on a schedule"
description: "Fetch two pages on a schedule, compare each to what was recorded last time, and report only what changed."
---

# Watch web pages for changes on a schedule

Build an agent that fetches a small set of pages, keeps a short summary of what
it saw, and on the next run says what changed - or that nothing did. The
fixture watches two pages you do not control but that change rarely: a
project's GitHub releases page and `example.com`. This is a procedure to run,
with two recorded fires as a reference.

Two fires prove two different things. **Run now** proves the comparison logic
works. It does not prove a *real* change is ever caught - only a fire that
lands after the page actually changed shows that, and this page cannot record
one on demand.

## What you need

- A [running installation](../install.md) with a model profile.
- No knowledge collection, no MCP connection and no sandbox connection: the
  workspace this recipe uses needs none of that. See below.

## Why not memory files

The obvious capability for "remember what I saw last time" is
[memory files](../reference/capabilities.md#memory-files). It does not work
here, and the reason is worth knowing before you reach for it on a schedule.

A trigger fire runs with its creator's role and grants, but not as them for memory: the run's *audience* - who will hear the answer - is
deliberately empty on the `schedule` surface, so an unattended run cannot read
or write the creator's personal notes. `write_memory` and `read_memory` both
answer:

```text
This conversation has no memory. It has no identified person and is not a
group chat, so a note would have to land somewhere other people read. Answer
from what you have rather than saving.
```

The same agent asked the same question in an ordinary chat saves the note
without trouble - the store exists there because a real person is listening.
On a schedule, nobody is.

## What to use instead

A [sandbox](../sandbox.md) workspace scoped to the **conversation** persists
across every fire of one trigger, because a trigger opens one conversation for
its whole life and appends every fire to it - the `conversation_id` a workspace
keys on does not depend on who is listening. The `state` backend needs no
sandbox connection: it is a small store in this deployment's own database, with
no shell and no container.

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, enable **Web fetch**. Restrict `allowed_domains` to
   `github.com` and `example.com`, so the agent cannot be asked to fetch
   anything else.
3. Enable **Files & shell**. Leave the backend on **Files** (the `state`
   backend - no shell, no sandbox connection) and the scope on **This
   conversation** - the defaults are exactly what this recipe needs.
4. Set a budget and a step limit for the trial. Each recorded fire cost about
   0.07-0.14 USD.
5. Set the instructions below, then **Publish**.

```text
You watch two pages for changes, once per run:
- https://github.com/vstorm-co/agenticos/releases
- https://example.com/

Each run:

1. Fetch both pages with web_fetch.
2. For the GitHub page, keep only the latest (topmost) release: its tag and
   title. For example.com, keep its heading and first paragraph. Ignore
   everything else on each page - star counts, timestamps, navigation.
3. Look for a file named watch-state.txt in your workspace.
4. If it does not exist, write it now with today's two summaries, one line
   per page, and report that you recorded a baseline - not a change.
5. If it exists, read it and compare each page's new summary to the line
   stored for it. Report, page by page, either the old and new value or
   "no change". Then overwrite watch-state.txt with the new summaries.
Never say a page changed unless the two lines you compared actually differ.
```

## Create the schedule

Open **Routines → New schedule**, or the agent's **Availability** tab, choose
the agent, and set a daily cadence. The prompt just needs to name the task:

```text
Run today's page check.
```

## Run it

Press **Run now** on the schedule twice, a few minutes apart. The first fire
finds no `watch-state.txt` and writes a baseline. The second reads it back and
compares.

!!! warning "Publishing a fix does not move a running schedule onto it"

    Publishing mints a version but does not repoint the [environment](../environments.md)
    a schedule reads from, unless that environment tracks latest - which
    `production` does not by default. If you edit the agent after creating the
    trigger, promote the new version to that environment (**Promote v2 to…**,
    with your version number) before the next **Run now**,
    or the fire still runs the version you just replaced.

## Check the result

| Check | Reference |
| --- | --- |
| First **Run now** | Reports a baseline, not a change, and neither page is said to differ |
| `watch-state.txt` after the first fire | Exists, with one line per page |
| Second **Run now** | Reads the same file back and reports "no change" for both pages |
| A page you edited between two fires | Reports the old and new value for that page only |
| The run's surface in Activity | `schedule` for both fires, same trigger, same run-log conversation |
| A run with `web_fetch` pointed at a third domain | Refused - `allowed_domains` does not include it |

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. The first **Run now** called
    `web_fetch` on both pages, then `read_file` on `watch-state.txt`, which
    failed because the file did not exist yet, then `write_file`. It reported
    the GitHub page's latest release as `v0.0.504` and example.com's heading and
    paragraph, and said this was a baseline. Cost: 0.13 USD. The second **Run
    now**, about a minute later, read the same file back, matched both
    summaries, and reported "No change" for both pages, then rewrote the file
    with the same content. Cost: 0.14 USD.

    The first attempt used `memory_files` instead of a sandbox, exactly as this
    page warns against: both fires called `read_memory` and got the "no memory"
    refusal above, and the agent correctly told the person reading the report
    that it could not save a baseline - rather than claiming it had.

## When it goes wrong

- **Every fire says "no prior state," never a comparison.** The workspace is
  not persisting. Check the scope is **This conversation**, not **Nobody** -
  the `run` scope opens a fresh, empty workspace every single fire.
- **`read_memory` or `write_memory` appears in the transcript at all.** Memory
  files is still bound. Remove it; it cannot do this job on a schedule.
- **A real page change is not reported.** Only a fire that runs after the
  change and after a fire that recorded the prior state catches it. Check the
  two fires either side of the change in Activity, not just the latest one.
- **Every fire reports a change, even when nothing moved.** The summary is too
  wide - a raw page fetch includes star counts, relative timestamps or a
  changing nonce that differs on every fetch. Narrow what the instructions keep
  to the one fact that matters.
- **The fire still behaves like the old version after you republished.** See
  the environment warning above.

## Record the trial

Keep the two page URLs, the instructions, the agent version, `watch-state.txt`
after each fire, and each run in Activity with its surface and cost. A person
still decides what counts as a change worth acting on, and watches the first
fire that lands after a real edit to confirm the comparison catches it - a
`Run now` pair only proves the logic, never that fire.
