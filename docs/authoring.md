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
- **Verify** your own edits: compare the draft with the version it is based on -
  the latest published one - against the same evidence, and say what the edits improve, what they risk and what they
  removed.
- **Improve a skill** or a **context file**: suggest a new body from the runs
  that read it.

The assistant is a [system agent](datasets.md#judge) of its own, listed with
the organization's other system agents. Its instructions can be edited like any
agent's, and its runs are ordinary runs: budgeted, priced and listed in Activity.

Expand **Authoring assistant** in Improve or Verify to choose a published
assistant. Changing the selection clears the previous estimate, so consent
applies to the chosen assistant's price and budget. `improver_agent_id` is kept
on the queued request; background improvement sessions accept the same choice.
The worker rechecks the selected agent's kind, publication and current caller
access. A deleted selection fails rather than reverting to the default.

## What it reads { #what-it-reads }

The assistant has no tools. What it reads is gathered for it, from the last 30
days of the agent's runs:

- answers people rated down, with their comments first;
- runs that failed, hit a budget or were blocked by a guardrail;
- answers rated up, as the contrast.

An unrated run that succeeded says nothing either way and is not read. Neither is
a test from the Builder's test panel, nor a delegate's run.

**It learns from training cases only.** Alongside rated chat runs, the assistant reads failed training answers, confirmed regressions, judge reasoning and Review notes from accessible [datasets](datasets.md). It receives training pass rates by tag and judge criterion, plus fixed and broken counts. Holdout questions, answers and grades never enter its prompt. Judge runs and the assistant's own runs remain excluded.

When there is more to read than fits one request, the runs are read in groups
first and the suggestions are written from what each group showed.

### Every quote is checked { #every-quote-is-checked }

Each suggestion carries a rationale and the evidence behind it: the runs it rests
on and quotes from them. Before anybody sees a suggestion, each quote is checked,
word for word, against the run it names. A quote that is not there, a run that is
not among those the assistant read, and anything past twelve items or six hundred
characters is dropped, and the suggestion says how many were. A reader without
`runs:view` sees which runs a suggestion rests on, not what was said in them.

The check proves that a quote is in its run, not that it bears on what it backs:
a real quote about something else passes it. So a Verify finding names the line
of the edit it is about, and the line must be part of the edit. The strip shows
that line above the finding's quotes, for the reader to judge whether they back
it. A finding that the edit is supported, left with no quote that could be
checked, is not shown.

When an Improve request finishes while the Builder is open, a result dialog shows the reviewed answer count, proposed and recorded changes, and rejected proposals with their reasons. You can reopen it with **Review result**. Changes show before and after side by side, with their rationale and linked evidence. An empty result says that nothing could be applied and shows no expected effect. Expected-effect prose containing raw run identifiers is replaced with a description counting the linked source answers.

After a check completes, readers with `runs:view` can compare answers from both arms in the dialog and open the full check. Before a check, it asks you to run one. An agent with no rated chat or training evidence has a compact assistant line above its instructions.

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

**Check with evals** runs a [dataset](datasets.md) against the draft's base - the
latest published version - with every waiting suggestion made, beside that
version in the same [eval run](evals.md#a-baseline-in-the-same-run). A guard can
hold production on an older version; the check never measures against it, so
what the latest version changed is on both sides and never blamed on a
suggestion. When the draft has moved from its base - edits of your own, or
suggestions accepted earlier - the draft itself is the baseline, run fresh rather
than taken from an earlier run, so the suggestions are the one difference; the
estimate prices that side too. The sides are named for what they are, in the
dialog and on the run: "v2 + 1 suggestion" against "v2", or "Draft + 2
suggestions" against "Draft". Nothing is accepted by checking, and the draft does
not change. While a waiting suggestion no longer
fits the draft, or clashes with another, the check is refused until it is
accepted or dismissed: the run measures exactly what waits.

Instead of a dataset, the check can run one of the agent's
[eval suites](evals.md#suites): its dataset, in its environment. The run compares
the two sides as any check does, and once it completes it
also says what the suite would have said: passed, failed or inconclusive, and
why, by the threshold the suite had when the check started. That shows on the
run and beside the check on the strip, worded as the suite's own results are.

The strip states each finished check in one sentence linking its run - "audit-smoke
would fail: breaks “Do you ship to Canada?”", or what it broke and fixed on the
dataset.

The check is not one of the suite's runs: it is in no suite's history and
notifies nobody, and the run's own verdict is what Accept goes by. A skill or
context change checked on a suite of the agent it runs on gets the same.

Each case has a fixed train or holdout assignment, preserved across dataset versions. Dataset settings choose the holdout share for future cases only (50% by default). Suggestion checks and improvement sessions measure only holdout cases and require at least five gradable questions. Copies of training questions or source evidence are excluded using normalized input and source run identity, including hand-entered and generated cases. Below the minimum, a session stops with `no_data` and says how many questions to add. The run labels both parts and excluded copies. Ordinary suites and promotion gates still count every case.

An improvement session pins its dataset version and chat evidence identities. Later rounds may learn from that version's training results, but new chats and new dataset cases cannot change its control sample.

A check counts as the draft's test once the draft is exactly what it checked -
every checked suggestion accepted and nothing else changed - so the publish
dialog reports its verdict; after a further edit it says that test is out of
date. A check measured against the draft itself never counts: it says nothing
of the draft against the published version it would replace. A check sends nothing to a dataset's [review queue](datasets.md#review) by
itself, since nothing was accepted; its run page says so beside **Send failed to
review**.

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
| Capabilities | Add or remove one, or change its settings - only where the settings are about quality alone, such as how much knowledge to retrieve or when to compact; settings that reach a URL, a domain, a connection, a provider or personal data never change, and Subagents are never added or reconfigured. A safeguard - Guardrails - can only be added: never removed or reconfigured, however the suggestion names it |
| Approval | Make a capability or one of its tools ask first |
| Specialists | Rewrite the description of an inline [specialist](reference/capabilities.md#delegation) |
| Knowledge bases | Bind or unbind one |
| Context files | Bind or unbind one |
| MCP tools | Change which tools of a bound server the agent may call |

Nothing else is a suggestion at all: eval suites and their thresholds, datasets,
budgets, observability and a pinned delegate are never changed by the assistant.
**Edit** works on a single value or a text - a setting, the step limit, a
description; anything else is accepted or dismissed as suggested.

### Widening access { #widening-access }

The assistant may suggest giving the agent more to reach: a capability, a
knowledge base, a context file, more MCP tools. Such a suggestion is marked
**Adds access** and names each thing it adds. It never widens what runs without
a person:

- A capability it adds arrives with each of its tools that changes something set
  to ask for approval, whatever the suggestion itself set them to.
- Allowing more tools of an MCP server makes a binding that asked for nothing ask
  for approval of the tools that write. **Undo** puts the tools back and leaves
  them asking: lowering the approval again is a person's decision. For a server
  each person reaches through their own account, a tool the assistant cannot see
  described counts as one that writes.
- Approval only tightens: a suggestion can make a capability or a tool ask first,
  never stop asking.

A suggestion that binds a knowledge base, a context file, a model profile or an
MCP server, or lets the agent call more MCP tools, is accepted only by somebody
who could make that change by hand: accepting it as anybody else is refused, as
the Builder would refuse it.

### A change of model { #a-change-of-model }

A suggestion to change the model says what one run would cost on each model,
priced from the agent's recent runs. Priced from fewer than five, it says it is
a rough estimate and from how many runs.

A change of model is accepted only after it has paid off. **Accept** stays
disabled, and says why, until a [check with evals](#check-with-evals) of exactly
what accepting leaves - the draft with every suggestion still waiting made - has
run on that model and found no confirmed regression. Dismissing another
suggestion or editing the draft makes the last check out of date, and a new one
is needed.

A check that left a case undecided - nothing graded it, or the provider or a
scorer failed on it - or reached no verdict holds it back too: grade the answers
or run the check again. So does a check the agent crashed on: fix what failed,
then run it again.

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
body on its next run. So **Check with evals** is the first action, on an agent
that uses the file, with only the file's body different, and **Apply** says
before you press it which agents and environments the change goes live for,
which eval suites it queues and which guards check it only at the next
promotion. Applying tells those agents' owners. A file edited
since the change was proposed cannot have the change applied: compare the two
and edit the file by hand, or ask the assistant again.

The assistant never proposes the body as it stands, and a new request rewrites
the change already waiting. Apply and Discard name the version of it you read,
and are refused once it changed since, for a skill change as for a file.

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

Activity retention keeps the combined cost of a session’s deleted paid runs, without keeping their questions or answers. Removing old activity never restores the spending limit. New checks and retries add to that retained amount; cancellation still leaves already incurred costs visible.

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

## Background improvement sessions { #background-improvement-sessions }

The API can coordinate an improvement in the background. First post a dataset
or suite and round limit to `/agents/{agent_id}/improvements/estimate`, then post
the same target with `budget_usd` to `/agents/{agent_id}/improvements`. The combined
estimate includes proposals, both eval sides, the judge, confirming reruns and
one repeat of an inconclusive comparison per round. Each paid step starts only
when its full estimate fits the remaining session budget. A started child is
allowed to finish, and actual costs remain visible even after cancellation.

Read the collection or an individual session to follow its stored timeline,
child IDs, verdicts and costs. The creator or an organization administrator can
post to `/{run_id}/cancel` under the same collection. The worker checks the
creator's current permissions, draft, latest publication, scoring and suite pin
before each transition. Changed inputs make the session stale; lost authority
stops it. Only one session can run for an agent at a time.

A checked improvement ends at `ready`, where its candidate becomes the waiting
suggestion batch. It never accepts, publishes or promotes. Earlier candidate
batches leave a person's waiting suggestions alone while checks run. A creator
notification links to the session when it becomes ready or stops.

Sessions make at most three rounds. A regression or unchanged result starts another proposal only if its complete forecast fits the remaining budget. Two unchanged rounds, an inconclusive comparison and its repeat, a previously tested candidate or the round limit stop the loop with a recorded reason. Training answers before and after inform the next round; holdout content remains hidden. Round costs are separate, and the best measured round prefers improvement, fewer newly broken questions, then higher settled success.

After completion, `/{run_id}/rounds/{number}/select` makes a measured round the waiting candidate, after checking the current base and access. Optional attribution has its own `.../attribution/estimate` and `.../attribution` actions. Starting requires `confirmed: true` and the reviewed `estimate_usd`; a higher fresh estimate is refused. It tests each pending change alone against the same base and pinned questions. Costs count against the session budget. Attribution does not accept, publish or replace the round's combined verdict.

Open **Improve** in the agent header or on the dashboard to start a session at `/agents/<agent>/improve/<session>`. The page can be closed and reopened while work continues. Choose test questions, review the complete estimate and confirm a spending limit before starting. Without questions, estimate and confirm writing a test set first; the baseline action tests today's answers. Advanced helper choices remain collapsed.

A failed proposal or eval can be retried explicitly with `/{run_id}/retry`; repeated clicks do not create another child. Automatic job retries never repeat a paid call. Human decisions update the session to accepted, published or rejected. The confirmed `/{run_id}/finish` action accepts the selected checked changes and optionally publishes in the same transaction. It can offer a publish-triggered suite with zero allowed regressions. Normal permissions and publish validation still apply, and guarded environments wait for their checks. Changes edited since measurement must be checked again.

Use **Include in the test** on the Changes screen to choose a subset. Estimate and confirm the new check before it spends anything; changing a choice or a suggestion invalidates the quote. The selected changes are measured against the same base and pinned questions. Earlier checks stay in the round history. Excluded or later suggestions remain undecided, and only the measured selection can be accepted. A selected recheck does not automatically request another proposal. Individual-change results attribute only differences confirmed by repeat answers; invalid or unfinished checks provide no attribution.

The session estimate includes sorting bad chat answers against writable knowledge bases bound to the agent, grouping their misses and reserving up to three proposed passages per base. The worker retains the requester’s current API-key scopes and checks the complete step estimate again before starting. Only frozen, unerased source chats reach classification, grouping or drafting; training failures remain agent evidence, and held-out text never reaches these helpers.

A failed classifier is shown explicitly and leaves the source conversations available. A session needing only knowledge stops with drafts to review, without creating an empty agent version. Checking a draft still requires its own estimate and confirmation; adding content remains a separate human decision.

A human review decision and its withdrawal recompute the current measured round in the same transaction as the test and suite results. The selected round and its spend remain unchanged. Earlier measurements and individual-change checks cannot replace the current combined verdict. No new model call, publication or environment move follows a review. If the original requester can no longer read the comparison, the cached round becomes inconclusive instead of retaining a green verdict. Live dataset events refresh the test, suite, session and environment views.

The step bar distinguishes completed work, running work, steps needing your decision, skipped work and steps not started. Select any step to inspect it; this does not start a paid action. Reopening a session shows its current work, while the bar keeps each step’s recorded state. On a phone the current step and its status appear below the markers.

Choose **Improve again** for another round, or **Raise the limit and continue** when a priced step did not fit. A fresh complete estimate and confirmation come before more spending; the sources, pinned questions and round cap remain unchanged. Retrying a failed step stays in the same round. A resumed test reserves only its remaining measurements, including any remaining inconclusive repeat. Paid parent restarts require the original requester and API-key identity, with current permissions checked again. **Discard** confirms dismissing only this session’s pending proposals. It leaves other batches alone and refuses to undo an applied change. Quotes announce no write; confirmed decisions refresh open agent pages.

### Proposing a new skill { #proposing-a-new-skill }

The assistant can propose **Worth creating a skill** when a reusable procedure appears in at least three distinct evidence answers. Each supporting passage must occur in the answer itself; reader comments alone do not establish a repeated procedure. The card shows its name, description, full body, rationale and verified evidence. A check binds a temporary skill to the candidate only: no skill row or published version is created.

**Accept** creates the private skill and binds it to the agent's draft in the same transaction. It requires `skills:edit` as well as edit access to the agent. Without creation permission the proposal remains readable and testable, but Accept explains why it is disabled. **Dismiss** creates nothing. **Undo** removes the binding and keeps the independent skill; accepting again reuses it only while its name and body still match. Skills contain written know-how and grant no tools. Additional tool access needs separate policy-checked proposals, with writing tools requiring approval.

The estimate reserves the full proposed body for each candidate answer and its confirming reruns, in addition to the historical per-answer price.

### Checking a knowledge draft { #checking-a-knowledge-draft }

In a finished session, choose a draft and independent questions about its topic. The estimate and confirmation are separate from accepting the agent changes. The test compares **A**, the selected agent changes, with **B**, the same changes plus the draft. Its result appears separately and says **assuming search finds this passage**: this stage injects the passage as context and does not test retrieval.

Training cases, source conversations, source turns and normalized copies of source questions are excluded. At least five independent, gradable holdout questions are required; otherwise the draft **cannot be measured** and no paid check starts. The complete quote includes both variants and confirming repeats, counts against the session limit and is bound to the current draft and selected questions.

**Unsupported — verify the facts** means the draft has no surviving source document in its knowledge base. A passing answer test does not prove its facts. Use the existing topic review dialog to check the passage and explicitly add it. Checking creates no context file or knowledge-base document and publishes nothing. Suites depending on the knowledge base still run after a person adds a document.

Temporary bodies are cleared when a check ends or its draft changes. Changed drafts invalidate the old verdict. Erasing a source person's data also clears derived test answers, scoring explanations and model manifests. A cancelled session cancels its knowledge checks too. These checks keep their paid cost after cancellation or erasure.

The draft records every input question as a fingerprint, including uncited inputs. Old drafts without complete provenance cannot be measured; write a new draft first. These fingerprints and source run identities are cleared with the draft during erasure.

#### Checking real retrieval { #checking-real-retrieval }

Choose **Test whether search finds it** to compare A against B with a retrieval-only overlay instead. The draft is embedded on the knowledge base’s selected model and added to its query candidates only during that run. Tenant restrictions, document allow-lists, business filters, ranking and final result limits still apply. No vector table, document or context file is created. Temporary content is removed even after failure or cancellation.

A new fix counts as demonstrated only if the draft reached every confirming candidate answer through the final search response. Otherwise the verdict is inconclusive, even when the grader liked the answer; the actual answers and grades remain visible. A search failure cannot become a success because the model ignored the tool error. The estimate includes extra embedding searches and their confirming repeats. An unavailable or unpriced embedding model refuses the check before paid work starts. A person must still verify the facts and explicitly add the document.

Manual tests and test-question generation notify their requester when they finish, including failures. Repeated job deliveries do not duplicate the notice. Suite and improvement child tests use their parent notification instead. Preferences for these events live under **Settings → Notifications**. Open test and dataset pages refresh through the live change feed after the outcome commits.

The wizard’s Understand step shows the bounded source sample, recorded cause, answer, reader comments and a conversation link. Unknown causes stay explicitly unclassified. The Test set step reads the session’s pinned question version, with training and held-out questions identified. Today shows the baseline only after a successful completed check; partial or failed checks never appear as a measured baseline. Source previews require `runs:view`, recheck current knowledge-base visibility and redact credentials in every text field.
