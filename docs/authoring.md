---
title: "Authoring assistant"
description: "The authoring assistant reads what people rated down and how runs ended, and suggests changes to an agent's instructions, tools, configuration, skills and context files. A person decides each one."
---

# Authoring assistant

The **authoring assistant** improves agents from evidence. It reads what people
rated down and how runs ended, and suggests changes to an agent's instructions,
to the names and descriptions of its tools, to its
[configuration](#configuration), and to the skills and context files it uses. It
never changes anything on its own: each suggestion waits for a person, an accepted
one lands in the [draft](concepts.md), and nothing reaches anybody until the
draft is published.

It does three things:

- **Improve** an agent: suggest changes from its rated-down and failed runs.
- **Verify** your own edits: compare the draft with the published version against
  the same evidence, and say what the edits improve, what they risk and what they
  removed.
- **Improve a skill** or a **context file**: suggest a new body from the runs
  that read it.

The assistant is a [system agent](datasets.md#judge) of its own, listed with
the organization's other system agents. Its instructions can be edited like any
agent's, and its runs are ordinary runs: budgeted, priced and listed in Activity.

## What it reads { #what-it-reads }

The assistant has no tools. What it reads is gathered for it, from the last 30
days of the agent's runs:

- answers people rated down, with their comments first;
- runs that failed, hit a budget or were blocked by a guardrail;
- answers rated up, as the contrast.

An unrated run that succeeded says nothing either way and is not read. Neither is
a test from the Builder's test panel, nor a delegate's run.

**It never reads evals.** Runs that answered an [eval](evals.md) case, the
judge's runs and the assistant's own runs are left out of what it reads, and it
never sees scores. A change checked by evals must not be fitted to the cases
that check it.

When there is more to read than fits one request, the runs are read in groups
first and the suggestions are written from what each group showed.

### Every quote is checked { #every-quote-is-checked }

Each suggestion carries a rationale and the evidence behind it: the runs it rests
on and quotes from them. Before anybody sees a suggestion, each quote is checked,
word for word, against the run it names. A quote that is not there, a run that is
not among those the assistant read, and anything past twelve items or six hundred
characters is dropped, and the suggestion says how many were. A reader without
`runs:view` sees which runs a suggestion rests on, not what was said in them.

## Suggestions { #suggestions }

Improve and Verify open the **assistant strip** on the agent's Build tab. Each
suggestion shows the passage it changes in its surroundings, why, and the
evidence, and each is decided on its own:

| Action | What happens |
|---|---|
| **Accept** | The change is written into the draft. Nothing is published. |
| **Edit** | Your own wording is accepted in place of the suggestion. |
| **Dismiss** | Recorded; a later request does not suggest it again. |
| **Undo** | Reverses the decision while it still fits the draft. |

A suggestion anchors on where its passage sat and what surrounded it, not on the
text alone, so a line that appears twice is changed where it was meant to be. If
the draft has moved on - the passage edited away, or a tool's description changed
by hand - the suggestion says it **no longer fits the draft** and can only be
dismissed. Undo refuses the same way once the accepted text was edited by hand: it
would throw that edit away.

A newer Improve replaces the waiting suggestions; Verify adds its suggestions to
them instead. Publishing the draft closes them: their decisions are final, and
the strip keeps them as a record.

A change the assistant proposes that cannot be recorded is not dropped
silently. The strip lists it under **proposed changes were not recorded**, with
why: the passage it changes is not in the instructions or occurs more than once,
the agent has no such tool, the setting is not one it may change. The worker logs
the same reasons. A passage copied with its quotes straightened, its backticks
dropped or its lines joined still finds the draft's own text.

### Check with evals { #check-with-evals }

**Check with evals** runs a [dataset](datasets.md) against the draft as it would
be with every waiting suggestion accepted, beside the published version in the
same [eval run](evals.md#a-baseline-in-the-same-run). Nothing is accepted by
checking, and the draft does not change. While a waiting suggestion no longer
fits the draft, or clashes with another, the check is refused until it is
accepted or dismissed: the run measures exactly what waits.

Instead of a dataset, the check can run one of the agent's
[eval suites](evals.md#suites): its dataset, in its environment. The run compares
the draft with the published version as any check does, and once it completes it
also says what the suite would have said: passed, failed or inconclusive, and
why, by the threshold the suite had when the check started. That shows on the
run and beside the check on the strip, worded as the suite's own results are.

The check is not one of the suite's runs: it is in no suite's history and
notifies nobody, and the run's own verdict is what Accept goes by. A skill or
context change checked on a suite of the agent it runs on gets the same.

The cases taken from the conversations the suggestions were derived from are left
out, and the run says how many: a change is never measured on the data it was
fitted to. A dataset made only of such cases is refused.

Each suggestion states the effect it expects. The strip shows it beside the eval
runs that checked the suggestions, so you can compare the prediction with what
the runs found.

## Configuration { #configuration }

Besides the text, the assistant can suggest a change to a few parts of an
agent's configuration. Each one is a suggestion like any other, decided on its
own in the strip, and shown by name: the model, knowledge base, context file,
capability or MCP server it refers to, never an identifier.

| Part | What a suggestion can do |
|---|---|
| Description | Set it |
| Model | Change the model profile |
| Model settings | Set temperature, top-p, max tokens, timeout or parallel tool calls |
| Step limit | Set `max_steps` |
| Capabilities | Add or remove one, or change its settings - only where the settings are about quality alone, such as how much knowledge to retrieve or when to compact; settings that reach a URL, a domain, a connection, a provider or personal data never change, and Subagents are never added or reconfigured. A safeguard - Guardrails - can only be added: never removed or reconfigured |
| Approval | Make a capability or one of its tools ask first |
| Specialists | Rewrite the description of an inline [specialist](reference/capabilities.md#delegation) |
| Knowledge bases | Bind or unbind one |
| Context files | Bind or unbind one |
| MCP tools | Change which tools of a bound server the agent may call |

Nothing else is a suggestion at all: eval suites and their thresholds, datasets,
budgets, observability and a pinned delegate are never changed by the assistant.
**Edit** works on a single value or a text - a setting, the step limit, a
description; anything else is accepted or dismissed as suggested.

### It never widens access { #never-widens-access }

A suggestion that binds a knowledge base, a context file, a model profile or an
MCP server, or lets the agent call more MCP tools, is accepted only by somebody
who could make that change by hand: accepting it as anybody else is refused,
as the Builder would refuse it. Approval only tightens: a suggestion can make a
capability or a tool ask first, never stop asking. A capability the assistant
adds arrives with each of its tools that changes something set to ask first, and
the suggestion lists those tools, as it does for MCP tools a change makes
reachable.

### A change of model { #a-change-of-model }

A suggestion to change the model says what one run would cost on each model,
priced from the agent's recent runs. Priced from fewer than five, it says it is
a rough estimate and from how many runs.

A change of model is accepted only after it has paid off. **Accept** stays
disabled, and says why, until a [check with evals](#check-with-evals) of the
waiting suggestions has run on that model and found no confirmed regression. A
check that decided nothing - an answer left ungraded, or no verdict - holds it
back too: grade the answers or run the check again.

## Skills { #skills }

A skill is improved from its workbench under Skills. What the assistant suggests
is a whole new body, and it waits with the other [skill](skills.md) changes
under Skills, with its rationale and evidence.

Applying a skill change is live: every agent bound to the skill reads the new
body on its next run. So a skill change can be checked with evals first, on an
agent that uses the skill: both sides run that agent's published version, and
only the skill's body differs. A change written against an older version of the
skill is refused once somebody has changed the skill since.

## Context files { #context-files }

A [context file](context.md) is improved from its editor on the Context page,
from the runs of the agents that read it. What the assistant suggests is a new
body, and it waits above the list on that page with its rationale and evidence,
and with the agents bound to the file - as far as you may see them. One change
waits for each file at a time.

Applying it is live, as for a skill: every agent bound to the file reads the new
body on its next run. So it can be checked with evals first, on an agent that
uses the file, with only the file's body different. A file edited since the
change was proposed cannot have the change applied: compare the two and edit the
file by hand, or ask the assistant again.

## Describing a new agent { #describing-a-new-agent }

The create dialog offers to describe the agent instead of filling in the form.
The description goes to the [Architect](console.md#the-assistant), which drafts agents and asks
before it creates one; the result is an ordinary draft.

## Cost and budget { #cost-and-budget }

Improve and Verify say what they would read and cost before anything is spent,
and start on a second click. The assistant has its own monthly budget, five
dollars when it is created, which an editor of the agent can change. A request
that would cost more than the assistant or the organization has left is refused
before anything is written.

On the dashboard, the spend line names what the assistant cost **on
improvements**, apart from what evals cost.

## Access { #access }

| To | You need |
|---|---|
| Start Improve or Verify on an agent | `runs:view`, edit access to the agent, and use of the assistant |
| Improve a skill | `runs:view`, edit access to the skill, and use of the assistant |
| Improve a context file | `runs:view`, `context:edit` on the file, and use of the assistant |
| Accept, dismiss or undo a suggestion | Edit access to the agent |
| Accept a suggestion that binds or reaches something | Also the access to bind it by hand |
| Apply or discard a skill change | `skills:edit` on the skill |
| Apply or discard a context file change | `context:edit` on the file |
| Check with evals | What an [eval run](evals.md#access) needs, and edit access to the agent |

Grants count: a member with an edit grant on one agent may improve that agent.

## When AI assistance is off { #when-ai-assistance-is-off }

With the organization's **AI assistance** switch off, the assistant does not run:
Improve, Verify and Improve on a skill or a context file are refused by the server, and the console
shows them disabled with a link to the switch. Suggestions already waiting can
still be accepted, dismissed and undone, and an eval run that needs no judge
still runs.
