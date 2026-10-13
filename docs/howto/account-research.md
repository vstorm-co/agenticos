---
title: "Brief yourself on a company before a call"
description: "Research a public organization with web search and web fetch, and get a one-page brief where every fact carries its source and its date."
---

# Brief yourself on a company before a call

Build an agent that researches an organization and writes a one-page brief
before a call with them: what they do, recent news, current leadership, and
what it could not confirm. The fixture is a well-known open-source foundation,
so you can check the brief against sources anybody can open. This is a
procedure to run, with one recorded run as a reference.

## What you need

- A [running installation](../install.md) with a model profile.
- Web search: the default method is DuckDuckGo and needs no account or key.
- No knowledge collection, no sandbox and no MCP connection.

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, enable **Web search** (method DuckDuckGo) and **Web fetch**.
3. Set a budget and a step limit for the trial. The recorded run used 20 steps
   and cost about 0.26 USD.
4. Set the instructions below, then **Publish**.

```text
You write a one-page brief on an organization before a call with them.
Research it with web search and web fetch before writing anything.

Rules:

- Every fact in the brief carries the source URL it came from, next to the
  fact, not collected in a list at the end.
- Next to each fact, name the date: either the date the source page itself
  states (an article date, a filing date) or, when the source carries none,
  the date you fetched it, marked as "(fetched)".
- Never state a person's name, title or any personal detail unless a source
  confirms it. If you cannot confirm who currently holds a role, say so
  instead of guessing, and do not use a plausible-sounding name.
- Do not repeat a home address, personal phone number or other private
  contact detail even if a source shows one. The brief covers the
  organization, not the people in it.
- End with a section called "Could not confirm" naming anything you looked
  for but did not find a source for. An empty section still gets the heading,
  with one line saying nothing was left unconfirmed.
```

## Run it

Open a new chat with the agent and send:

```text
Brief me on the Python Software Foundation before a call with them.
```

Any well-known public organization works the same way - a large open-source
foundation is a good default because its finances, board and mission are all
published and stable enough to check.

## Check the result

| Check | Reference |
| --- | --- |
| Every factual claim | Has a source URL right next to it |
| Every claim's date | States the source's own date, or says "(fetched)" when the source has none |
| Named people | Only ones a source confirms, sourced to that organization's own page rather than a guess |
| A role nobody could confirm | Says so plainly rather than naming a plausible person |
| Personal contact details | Absent, even if a source surfaced one |
| "Could not confirm" section | Present, naming a real gap - not empty by omission |
| The same question about an organization with almost no public footprint | Says so and produces a short, honestly thin brief rather than inventing detail to fill the page |

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. The agent ran three
    `web_search` calls, then `web_fetch` on the PSF's own about, board and
    2024 annual report pages, plus a grants-program post and a Form 990
    aggregator. One `web_fetch` (a filings site) failed and was not retried
    with a different source for that fact.

    The brief cited a source next to every claim - mission, programs, FY2024
    financials, the 2024 grants total, and the full board roster, each dated
    either from the source or marked "(fetched)". It named the board only from
    the PSF's own roster page. For the highest-compensated person named in a
    Form 990 search snippet, it explicitly declined to state the name because
    the filing itself was not directly reachable, and listed that gap, plus
    the exact revenue breakdown and the next PyCon's dates, under "Could not
    confirm". Cost: 0.26 USD.

## When it goes wrong

- **A person is named with no source next to them.** Tighten the instructions
  to require the source at the point of the claim, not merely somewhere in the
  reply - a model that read a name in passing while researching something else
  can still repeat it without meaning to.
- **The brief has no "Could not confirm" section.** The instructions were not
  followed, or nothing was searched for that could plausibly be missing -
  check the transcript's tool calls before trusting a brief that found
  everything.
- **A `web_fetch` fails and the fact simply disappears.** The model moved on
  rather than trying a second source. Ask it to name what it could not fetch,
  which is exactly what the recorded run's Form 990 gap looked like.
- **Financial or leadership facts read as current but are a year old.** Check
  the date next to each one - a page with no publish date and a fetch date
  attached is not the same claim as one dated to the source.
- **The same organization gets a different board on a repeat run.** Web search
  results are not stable between runs; check which page each name came from
  before trusting either version, and prefer the organization's own page over
  a search snippet.

## Record the trial

Keep the question, the brief, the sources it cited, the run in Activity with
its tool calls, and the cost. A person still reads the brief against its own
sources before a call, decides whether a "could not confirm" gap matters
enough to look up by hand, and never repeats an unconfirmed personal detail
even if a later run states one confidently.
