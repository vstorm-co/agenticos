# Clock

Puts the current date and time in the agent's instructions. Contributes no
tools.

## Why not a tool

It was one - `current_datetime` - and that was the wrong shape.

The current time is context, not an action. A tool makes the model *decide* to
look it up, and a model that has to decide usually does not: it answers from
whatever date its training left it with, confidently and wrongly. The failure
is silent, because a plausible wrong date reads exactly like a right one.

It is also a whole round trip - a model request, a tool call, a second model
request - to retrieve one line the server already knew before the run started.
Every conversation pays for that, or skips it and gets the wrong answer.

As instructions, the agent simply knows. There is nothing to skip.

## Why it is resolved per request

`get_instructions` returns a callable, not a string. A string would be built
once when the agent was assembled, so a conversation open for an hour would
keep telling the model the minute it started with - the same class of bug,
quieter.

## Configuration

| Field | Default | What it is |
|---|---|---|
| `timezone` | `UTC` | IANA zone the agent thinks in, e.g. `Europe/Warsaw` |

Timezone is configuration because "today" is not a UTC question. For a team in
Warsaw a run at 00:30 CEST is still the previous day in UTC, and an agent
reporting yesterday's date is wrong in a way nobody catches until it schedules
something.

An unknown zone is refused when the capability is built, so it fails while
somebody is looking at the Builder rather than mid-run in front of a user.
Configuration reaches this from a JSON spec, so the type annotation guarantees
nothing on its own.

## Format

`2026-07-27 10:59:03 +0200 (CEST)` - ISO-8601 date, then time, offset and zone
name. Not prose: a model asked to compute "14 days from now" does noticeably
better arithmetic on `2026-07-27` than on `27 July 2026`, and an offset without
a zone name is an invitation to guess.

## What this deliberately does not do

Timezone conversion, business-day arithmetic, "what time is it in Tokyo".
Those are computation, and computation is what a tool is for - but it would be
a different capability with its own reason to exist. This one answers exactly
one question, and answers it before it is asked.
