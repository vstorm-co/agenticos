---
title: "Research a question with subagents and publish a report"
description: "Split a question into independent sub-questions, delegate each to a one-off specialist, and publish a sourced comparison as an artifact."
---

# Research a question with subagents and publish a report

Build an agent that splits a question into independent parts, hands each part to
its own specialist, and writes a report from what comes back. The fixture is a
comparison of three open-source licences: a stable, public topic where every
claim can be checked against the licence text itself. This is a procedure to
run, with one recorded run as a reference.

## What you need

- A [running installation](../install.md) with a model profile.
- Web search: the default method is DuckDuckGo and needs no account or key.
- No sandbox, no knowledge collection and no MCP connection.

## Prepare the input

The question splits into three independent sub-questions, one per licence. Ask:

```text
Compare the MIT licence, the Apache License 2.0 and the GPLv3 on one question:
when you distribute software that includes code under that licence, what are
you obligated to do - include the licence text, state changes you made, or
disclose or release your own source code?
```

The reference answer, so you can check the agent's report by hand:

| Licence | Include licence text | State changes | Release your source |
| --- | --- | --- | --- |
| MIT | Yes | No | No |
| Apache-2.0 | Yes, plus the `NOTICE` file | Yes, per file | No |
| GPLv3 | Yes | Yes, per file | Yes, for the whole combined work, on distribution |

GPLv3's source obligation is triggered by distribution, not by modification: an
organization that only runs a modified copy internally owes nobody a release.

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, enable **Delegation**. Turn on `allow_dynamic` - the setting
   that lets the model invent a one-off specialist for a sub-question nobody
   pre-wrote a specialist for. Set the mode to **Async**, so the three
   sub-questions run at once instead of one after another, and leave the
   fan-out ceiling at 3.
3. Still on Delegation, toggle **Share Web search with delegates** and
   **Share Web fetch with delegates**. A specialist the model invents gets no
   capabilities of its own [by design](../reference/capabilities.md#delegation) -
   only what the parent explicitly shares reaches it, so without this step
   every invented specialist could delegate but could not search.
4. Enable **Web search** (method DuckDuckGo) and **Web fetch** on the parent
   itself - sharing only reaches a delegate what the parent is bound to.
5. Enable **Planning** and **Artifacts**.
6. Set a budget and a step limit for the trial. The recorded run used 40 steps
   and cost about 0.43 USD.
7. Set the instructions below, then **Publish**.

```text
You research a question that splits into independent sub-questions.
Write a plan naming each sub-question as its own step.
For each sub-question, call delegate to create a one-off specialist with
mode="async": give it a narrow instruction (research exactly this one
sub-question, using web search and web fetch, and answer with a short sourced
summary), a clear name, and no capabilities argument.
After firing all the sub-questions, call wait_tasks for all of them before
writing anything.
Every claim in your final report must carry the source URL it came from.
State plainly where the sources disagree or where you could not find an answer.
Publish the finished report with publish_artifact under the name
licence-comparison.
Do not answer from your own training knowledge without a source URL next to it.
```

## Run it

Open a new chat with the agent and send the question from *Prepare the input*.

The model calls `delegate` three times, once per licence - each one is its own
delegation, not a single call doing all three. **Delegate is side-effecting**,
so all three park for approval together, as one model step can park several
calls at once. Read the three proposed specialists, then **Approve**. The run
resumes, fires the three specialists in the background and calls `wait_tasks`
to collect them before it writes the report.

## Check the result

| Check | Reference |
| --- | --- |
| Number of delegations | Three, one per licence, each its own row in Activity under the parent run |
| MIT obligation | Include the licence text and copyright notice; nothing else |
| Apache-2.0 obligation | Licence text, `NOTICE` file, and a per-file changed notice |
| GPLv3 obligation | Licence text, per-file changes, and the complete source on distribution |
| Every claim | Carries a source URL next to it, not collected in one list at the end |
| Disagreement or gap | The report says so explicitly, or states there was none |
| Artifact | **Artifacts** lists `licence-comparison`, private to you |
| A two-part question with only one real source (e.g. asking about a licence that does not exist) | The report says it could not confirm that part, rather than inventing an answer |

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. The agent wrote a four-step
    plan, then called `delegate` three times in one turn - `mit-licence-research`,
    `apache2-licence-research`, `gplv3-licence-research` - all async. All three
    parked for approval in one step; after approval the run called `wait_tasks`
    and got `3/3 finished`. The report matched the reference table exactly, cited
    the OSI, Apache.org, GNU.org and FSF FAQ pages, and closed with "No source
    disagreements found" naming the sources that agreed. It published
    `licence-comparison` as an HTML artifact. Total cost: 0.43 USD, all three
    delegations included - no separate `agent_runs` row exists for a dynamic
    specialist, since it is not a published agent.

## When it goes wrong

- **A delegation is refused outright, not parked.** Delegation is off, or
  `allow_dynamic` is off and the model tried `delegate` or `create_agent`
  anyway - only `task` is offered to a delegation with neither.
- **A specialist reports it has no search tool.** `share_with_delegates` was
  not set, or it names a capability the parent itself is not bound to -
  publishing refuses the second case, so this is usually the first.
- **The three sub-questions run one after another, not together.** The mode is
  `sync`, or the model chose `mode="sync"` on its own `delegate` calls despite
  the instructions.
- **Only one delegation appears, covering everything.** The model treated the
  three-part question as one task instead of splitting it - tighten the
  instructions to name delegating each part separately, not just researching it.
- **The run stops with "reached the fan-out ceiling."** More than `max_fanout`
  delegations were fired in one turn; three sub-questions fit the default of 3,
  but a fourth would not.

## Record the trial

Keep the question, the plan the agent wrote, each delegation's name and result,
the sources cited, the artifact and its version, and the cost from Activity. A
person still reads the artifact against the reference facts before trusting it,
decides who may read it, and judges whether the "could not confirm" section is
honest or is hiding a search that should have been tried again.

## Next steps

Once this works on a topic with a known answer, point it at a question with no
fixed reference and rely on the "state where sources disagree" instruction
instead of a table you already know. To keep the report current, continue with
[schedule a weekly report](scheduled-report.md).
