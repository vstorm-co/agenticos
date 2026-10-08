---
title: "Build a personal assistant that remembers you"
description: "Give an agent memory of your own preferences, check that a later conversation applies them, then confirm it can forget one on request."
---

# Build a personal assistant that remembers you

Build an assistant that keeps its own notes about the person it talks to, across conversations, with nothing to connect and no external account. State a few synthetic preferences, open a new conversation and check the assistant uses them, then ask it to forget one. This is a procedure to run, with one recorded run as a reference.

## What you need

- A [running installation](../install.md) with a model profile.
- No sandbox, no embedding model and no MCP connection — [memory files](../reference/capabilities.md#memory-files) work with nothing bound.

## Prepare the input

These are invented facts about a fictional person, small enough to check against the assistant's own replies:

```text
Timezone: Europe/Warsaw
Meeting-free day: Friday
Summary format: short bullet points, not paragraphs
```

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, enable **Memory files**, **Date and time** and **Conversation search**. Add **Web search** if you want the brief below to look anything up; the checks here do not need it.
3. Set a budget and a step limit for the trial. The recorded runs used 5–15 steps and cost about 0.01–0.04 USD each.
4. Set the instructions below, then **Publish**.

```text
You are a personal assistant that remembers what this person tells you about themselves.
When the person states a preference or a standing fact (timezone, working hours, meeting-free days, how they like summaries formatted), save it with write_memory under a short name, then read MEMORY.md and add or update a one-line entry for it with edit_memory (or write_memory if MEMORY.md does not exist yet).
When asked for a plan, a summary or a morning brief, apply every preference currently in your notes: check MEMORY.md, read any note it lists that is relevant, and follow it without being asked again.
When asked to forget something, delete the matching note with delete_memory, remove its line from MEMORY.md with edit_memory, and confirm in one sentence what you forgot.
Never save something the person has not actually told you.
```

`write_memory`, `edit_memory` and `delete_memory` are side-effecting, so each save or forget parks for **Tool approval required** by default, the same as any other write. Approve it to continue.

## Run it

**Conversation 1** — state the preferences:

```text
A few things about me: I'm in the Europe/Warsaw timezone, I keep Fridays meeting-free, and I prefer summaries as short bullet points rather than paragraphs.
```

**Conversation 2** — a fresh conversation with the same agent, asking it to use what it learned:

```text
Give me a plan for tomorrow. I have three things to fit in: a client call, writing a proposal, and a team sync.
```

**Conversation 3** — ask it to forget one of the three:

```text
Forget my meeting-free Fridays preference.
```

A schedule can read this agent's instructions but not its owner's notes — see [what a schedule cannot read](#what-a-schedule-cannot-read) before you wire a morning brief to one.

## Check the result

| Check | Reference |
| --- | --- |
| Conversation 1's reply | Confirms all three preferences, after approving three `write_memory` calls and one that writes `MEMORY.md` |
| `MEMORY.md` after conversation 1 | Lists `timezone`, `meeting_free_days` and `summary_format` |
| Conversation 2's plan | Uses Europe/Warsaw, is mostly bullet points, and does not misapply the Friday rule to a day that is not a Friday |
| Conversation 3's reply | Names what it forgot, in one sentence |
| Settings → Memory (or `GET /memory/mine`) after conversation 3 | `meeting_free_days` is gone entirely; the other two notes are unchanged |
| A morning-brief schedule's own **Run now**, before it has ever been told anything in chat | Says nothing is on file rather than guessing — see below |

Open Activity for each run and check the tool calls, not only the reply: a `write_memory` the model called but nobody approved never happened.

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. Conversation 1 called `write_memory` three times, then, once approved, wrote `MEMORY.md` as `- timezone [preference] — …`, `- meeting_free_days [preference] — …`, `- summary_format [preference] — …`. Cost 0.039 USD.

    Conversation 2 called `read_memory` on all three notes and `search_conversations` (which found nothing, correctly — nothing had been said about tomorrow yet), then answered with a bulleted schedule in Europe/Warsaw time and noted that tomorrow was a Saturday, so the meeting-free rule did not apply. Cost 0.026 USD.

    Conversation 3 called `delete_memory` on `meeting_free_days`, then, once approved, `read_memory` and `edit_memory` on `MEMORY.md` to drop its line, and answered "Done — I've forgotten your meeting-free Fridays preference and removed it from my index." `GET /memory/mine` afterwards listed only `timezone` and `summary_format`. Cost 0.043 USD.

## What a schedule cannot read

A scheduled or event-triggered fire runs with the creator's own role and grants, but it is nobody's conversation for memory: `list_memory` on a **Run now** of a morning-brief schedule answered "This conversation has no memory. It has no identified person and is not a group chat, so a note would have to land somewhere other people read" — the same refusal an anonymous widget visitor gets, even though the schedule's creator is a real, known member. If a scheduled brief needs a preference, state it in the schedule's own prompt, the way [a scheduled report](scheduled-report.md) states its data in the message rather than depending on memory or a file nobody re-supplies.

## Who can read this

Nobody reads your notes by organization role — not an Owner, not an Admin, not someone holding an edit grant on this agent. You reach your own at **Settings → Memory** (`GET /memory/mine`), where you can stop using a note, use it again, or delete it outright; "stop using" keeps it on the page for you while it no longer reaches any model. Only a deployment administrator can read somebody else's, one person at a time, and that read is written to the audit trail with the actor, the subject and a reason — never the content. See [whose notes, and who may hear them](../reference/capabilities.md#whose-notes-and-who-may-hear-them) and [reading it, and erasing it](../reference/capabilities.md#reading-it-and-erasing-it).

In a group chat the rule changes: the notes belong to the room and everyone in it reads them, and nothing said to the assistant alone is read back there. This trial only used one-to-one web chat, where the store is yours alone.

## When it goes wrong

- **A save or a forget never happens.** `write_memory`, `edit_memory` and `delete_memory` are side-effecting and gated by default; check **Approvals** in Activity for a parked call before assuming the model ignored the instruction.
- **A later conversation does not know a saved preference.** Check `MEMORY.md` itself — a note the agent saved but never indexed is invisible until the model calls `list_memory`, which a lighter model may not do unprompted.
- **A scheduled brief guesses instead of using your notes.** Expected — see [what a schedule cannot read](#what-a-schedule-cannot-read) above. Put the fact in the schedule's prompt.
- **Deleting a note does not remove it everywhere.** `delete_memory` drops the note itself; if `MEMORY.md`'s line naming it is not also rewritten with `edit_memory`, the index still describes something that is gone.

## Record the trial

Keep each conversation, the agent version, which `write_memory`/`delete_memory` calls were approved, and `GET /memory/mine` before and after the forget request. A person still approves every save and deletion, decides whether **Allow personal memory** stays on for this agent, and judges whether a plan actually reflects what was stated — the assistant does not check itself.

## Next steps

To reach this assistant from a schedule instead of web chat, read [what a schedule cannot read](#what-a-schedule-cannot-read) first, then [schedule a weekly report](scheduled-report.md) for the mechanics of a cadence and a run-log conversation. To let it search what was actually said in past conversations rather than only what it chose to save, see [conversation search](../reference/capabilities.md#conversation-search).
