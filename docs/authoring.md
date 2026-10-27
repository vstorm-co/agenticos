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

- **Improve** an agent: suggest changes from its rated-down and failed runs. In the
  console every **Improve** opens the [Improve wizard](#the-improve-wizard); a
  one-off request is still available through the API.
- **Verify** your own edits: compare the draft with the version it is based on -
  the latest published one - against the same evidence, and say what the edits improve, what they risk and what they
  removed.
- **Improve a skill** or a **context file**: suggest a new body from the runs
  that read it.

The assistant is a [system agent](concepts.md#system-agents) of its own, listed with
the organization's other system agents. An administrator edits its instructions
like any agent's - changing a system agent takes `org:settings` - and its runs
are ordinary runs: budgeted, priced and listed in Activity. It is never the
agent an Improve or a Verify is about. Set to
[search the knowledge base](concepts.md#system-agent-spec), it reads the
knowledge bases of the agent it improves.

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

When an assistant request - a Verify, or an Improve through the API - finishes while the Builder is open, a result dialog shows the reviewed answer count, proposed and recorded changes, and rejected proposals with their reasons. You can reopen it with **Review result**. An empty result says that nothing could be applied and shows no expected effect. Expected-effect prose containing raw run identifiers is replaced with a description counting the linked source answers.

Every changed text - instructions, a tool description, a context file - shows as a diff: removed and added lines with the changed words marked, a few unchanged lines around each change and the rest folded, unified or side by side on a wide screen. Each change keeps its rationale and linked evidence; run identifiers in a rationale show as numbered conversations.

After a check completes, readers with `runs:view` can compare answers from both arms in the dialog and open the full check. Before a check, it asks you to run one. An agent with no rated chat or training evidence has a compact assistant line above its instructions.

## Suggestions { #suggestions }

Suggestions from an improvement session, a Verify or the API wait on the
**assistant strip** on the agent's Build tab. Each
suggestion shows the passage it changes in its surroundings, why, and the
evidence, and each is decided on its own:

| Action | What happens |
|---|---|
| **Accept** | The change is written into the draft. Nothing is published. |
| **Edit** | Your own wording is accepted in place of the suggestion. For instructions, the whole text opens: the current version beside the proposed one you edit, with the diff redrawn as you type. Only the suggested passage is saved; text outside it is changed in the instructions editor. |
| **Dismiss** | Recorded; a later request does not suggest it again. |
| **Undo** | Reverses the decision while it still fits the draft. |

A suggestion anchors on where its passage sat and what surrounded it, not on the
text alone, so a line that appears twice is changed where it was meant to be. If
the draft has moved on - the passage edited away, or a tool's description changed
by hand - the suggestion says it **no longer fits the draft** and can only be
dismissed. Undo refuses the same way once the accepted text was edited by hand: it
would throw that edit away.

The strip has two tabs, each with a count. **To review** shows every suggestion
still waiting, whole. **Decided** folds each accepted, edited or dismissed one to a
line naming the kind of change - Instructions, a tool description, a setting, a new
skill - how it was decided and what it was for; opening the line shows the change
and Undo. Both tabs group changes by kind. The strip opens on To review, or on
Decided once nothing is left to review.

A newer Improve replaces the waiting suggestions; Verify adds its suggestions to
them instead. Publishing the draft closes them: their decisions are final, and
the strip stops showing them and the rest of what the assistant reported before
the publication, since all of it was about a draft that is now a version. They
stay stored with their decisions. A request still running when the version is
published shows what it finds once it finishes.

A change the assistant proposes that cannot be recorded is not dropped
silently. The strip lists it under **more ideas the assistant did not add**, with
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

Each case has a fixed train or holdout assignment, preserved across dataset versions. Dataset settings choose the holdout share for future cases only (50% by default). Suggestion checks measure only holdout cases; an improvement session splits the questions again for each of its attempts, by the same share, and measures each attempt on its own held-out part. Both require at least five gradable held-out questions.

Copies of training questions or source evidence are excluded using normalized input and source run identity, including hand-entered and generated cases. Below the minimum, a session stops with `no_data`, or refuses the step that would test too few, and says how many questions to add. The run labels both parts and excluded copies. Ordinary suites and promotion gates still count every case.

An improvement session pins its dataset version and chat evidence identities. A later attempt learns from the training results of its own split, so a question one attempt kept aside may help write the next; new chats and new dataset cases cannot change what the session measures. Attempts measured on different questions are compared by what each changed against its own baseline, not by their pass rates.

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

An improvement session goes one step at a time and waits for a person between
steps; it never accepts, publishes or promotes. Post a dataset or suite to
`/agents/{agent_id}/improvements/estimate`, then post the same target with
`budget_usd` to `/agents/{agent_id}/improvements`. The budget caps the whole
session. Starting pays only for reading what went wrong: the session sorts the
bad answers, groups their misses into knowledge [topics](knowledge-gaps.md#topics)
and stops after **Understand** with the status `waiting`.

From a stop, post `budget_usd` to `/{run_id}/continue/estimate` for the price of
the step that would start, then post that quote with `confirmed: true` to
`/{run_id}/continue`. After **Understand** the next step writes the changes and
stops again after **Changes**. There, `PUT /{run_id}/selection` with `hunk_ids`
chooses the changes to test and `PUT /{run_id}/changes/{hunk_id}` with
`edited_text` tests a wording of your own instead of the helper's; both are free.
The next step then tests the chosen changes.

A price that moved since the quote
is refused with the new one, to confirm again. A step that does not fit what is
left of the budget is refused and the session keeps waiting: raise `budget_usd`
and estimate again. A started step is allowed to finish, and actual costs remain
visible even after cancellation.

The test runs on its own: the agent as it is and the changed one answer the same
questions, and an inconclusive comparison is asked once more within the test's
price. It ends at the result: `ready` when the attempt made the agent better, its
changes then the waiting suggestion batch, and `stopped`, with the verdict as the
reason, otherwise.

No attempt starts by itself. **Try again** is the same
`/continue` from the result, with an optional `note` the helper reads beside the
evidence; the attempt writes new changes and stops after **Changes**, since
**Understand** is read once per session. A session makes at most three attempts
within its budget. Two unchanged results in a row, or an inconclusive one and its
repeat, show on the result as a hint that another attempt is unlikely to help, not
as a stop.

Whoever may start a session on the agent - edit access, `runs:view` and AI
assistance on - may take its next step or try again. The session records who did,
and the steps after it run with that person's current permissions and credential,
so a session the Architect started can be taken further in the console.

The worker
checks the draft, latest publication, scoring and suite pin before each
transition: changed inputs make the session stale at once, and lost authority
stops it.

A session waiting at a stop, stopped or failed is also made stale as soon as its agent or test set changes under it; a ready one, whose draft moves while its candidate is decided in the Builder, closes only after its week. A session left at a stop or at its result for seven days closes as stale,
with the reason `expired`. An agent has one open session at a time - queued,
running, waiting, ready, stopped or failed - so starting another answers `409`
until the open one ends. The creator or an organization administrator can post to
`/{run_id}/cancel`.

The person who took the last step is notified at each stop and each end: the
analysis read, changes ready to review, a checked result, stopped, failed or stale,
decided outside the wizard, and a finished knowledge or attribution check. Read the
collection or an individual session to follow its stored timeline, child IDs,
verdicts and costs; an open session page follows each stage through live change
events.

Every attempt keeps questions of its own aside. The test questions are split again
for each attempt - the dataset's share of them, drawn from the session and the
attempt, so one attempt always draws the same ones - and the split is frozen when
its test starts: the repeat of an inconclusive comparison, a test of chosen
changes, individual-change checks and a knowledge draft's check all measure on it.

Each attempt needs at least five gradable questions kept aside, and the step that
would test fewer is refused with how many to add. The helper reads the answers to
an attempt's other questions, never the ones kept aside. Since attempts are
measured on different questions, the result compares them by what each changed
against its own baseline - newly fixed minus newly broken, over how many questions
it kept aside - and an attempt's pass rate stays in its details. The best attempt
has the best verdict, then the largest such change.

After the result, `/{run_id}/rounds/{number}/select` makes a measured attempt the
waiting candidate, after checking the current base and access. Optional
attribution has its own `.../attribution/estimate` and `.../attribution` actions.
Starting requires `confirmed: true` and the reviewed `estimate_usd`; a higher fresh
estimate is refused. It tests each pending change alone against the same base and
the attempt's questions. Costs count against the session budget. Attribution does
not accept, publish or replace the attempt's combined verdict.

### The Improve wizard { #the-improve-wizard }

Open **Improve** in the agent header or on the Build tab's assistant strip, from the **Needs attention** badge on the agent list, from the dashboard card or from the agent's **Knowledge gaps** tab. It sits among the header's other actions; when the version it serves now had answers rated down or failed runs in the last 30 days, it wears a dot and its name says why. The dashboard card **Improvements waiting for you** lists the sessions stopped for a decision.

Every **Improve** opens the agent's open session - working, waiting for you, at its result, or stopped or failed - and starts a new one once that session is kept as a draft, published, discarded, cancelled or closed, after which it stays in the agent's [improvement history](#improvement-history). **End it and start a new one** beside an open session ends it first.

A session lives at `/agents/<agent>/improve/<session>`; the page can be closed and reopened while work continues. Each screen asks for at most one decision, names who decided what on it, and keeps advanced options under **Show details**. Each screen leads with figures and small charts, every state marked with an icon as well as a colour; full answers, quotes and reasons wait in cards that open. One line above the steps gives the session's state - **Working** while a step runs, and at a stop what it waits for: **Waiting for you: look at what went wrong** or **Waiting for you: review the changes** - and what it has spent of its limit.

A step opens once it has work to show or a decision to ask for; the page follows the step the session is on, and after you open another one, **Go to the current step** brings it back. At a stop the footer holds the next step with its price, for example **Next step: write the changes · about $0.04**; nothing is spent before you press it. When the price moved since it was shown, the footer says so - **The price changed to about $0.05. Press again to go on.** - and when the step costs more than the session has left, it offers to raise the session's limit right there.

**Start.** Three figures from the last 30 days, then the agent's own test questions, already chosen and priced: the estimate covers reading what went wrong, with about how long that takes, appears without a click and spends nothing, so **Start improving** is the one decision. Each next step is priced before you press it, and the limit caps the whole session. Other test questions, the spending limit, the helper and a test of today's answers sit under **Show details**. An agent without test questions gets **Write test questions for me**: rated answers become questions, more are written for topics with no example, and the estimate follows once they are ready. When too few questions are left to measure a change, it offers to write as many more as the session lacks. The hint after a first publish opens this screen to set a baseline.

1. **Understand.** One sentence and a bar count the problems to fix in the agent and the information missing from the knowledge base. Examples whose misses joined one knowledge gap topic form one card, and so does a question asked both as a test question and in a conversation. A card shows the question and opens to the answer, the comments, how a test answer was graded - the grade the judge gave each criterion, and whether each rule was met - and why it counts: the grades it failed, how a person rated it, and why the classifier put it there. Answers rated up, or in which the classifier found nothing wrong, are sorted under **Not a problem to fix** automatically; nothing on this step is set by hand. An answer whose topic a document has covered since counts under **Already in the knowledge base**, with that document and the day it was added: nothing is left to draft for it. The session always stops here; **Next step: write the changes** asks the helper for changes.
2. **Changes.** How many changes were proposed and how many are included, then each change as a diff with Should fix, Why and Based on folded under it. At the stop each change has **Include change N in the test**, of which at least one stays ticked, and **Change the wording**, which tests your wording instead of the helper's: the change is then marked **Reworded by you**, and **Back to the proposed wording** undoes it. **Next step: test the selected changes** starts the test; while it runs, the list can be read but not changed. Knowledge drafts form their own column, holding the drafts somebody asked for. When no change was found, the screen lists what each attempt tried.
3. **Check.** The agent as it is today and the changed one answer the same questions in one test, each with a bar of how far it has got; answers from a test run before the session started fill today's bar at once. Then the stages, each marked done, running or not started: asking, grading, and re-asking the answers whose result changed. The test runs on its own and the result opens when it is done. **Open the full check** leads to the eval run.
4. **Result.** What the session came to comes first, in sentences built from the verdicts - which attempt made the agent better, or that none did and which made it worse - with the topics missing from the knowledge base and why the session stopped; once decided, it says which attempt was published as which version, or kept as a draft. Under **What you can do** sits one primary action: **Review and accept the changes** when a checked candidate waits, **Try again** while attempts or budget are left, **Draft the ones you need** when only knowledge is missing, and otherwise **End without changes**, beside **Start a new session** and a hint to add test questions where the agent answers badly. A failed step offers **Retry this step within the spending limit** first. With two attempts or more measured, **Which attempt to keep** lists them with the kept one ticked; choosing another asks for **Keep attempt N**, and an attempt that was not better first says what accepting it costs - the questions it broke, or that it brings no measured gain. A decided session lists them without the choice. **Try again** takes an optional **Note for the helper** - what to change or keep - and its price before it starts; the new attempt stops at **Changes**. A step stopped because whoever took it lost the access it needs offers **Continue this step with my access**, to anyone who may start a session. Then the figures: newly fixed and newly broken count only changes confirmed by asking again, with the ones not confirmed yet in small type beneath - changed once, but not the same way when asked again, and the count of topics missing knowledge leads to their list. Each attempt is one closed row - its verdict, what it fixed and broke against its own baseline out of the questions it kept aside, what writing and testing it cost - the session's total, analysis included, sits above the list - and the best attempt marked - or, when a person chose an attempt that was not better, marked as chosen. Every attempt keeps aside its own questions, so attempts are compared by their change rather than by their pass rates, which appear only in a row's details. A row opens to the bars of questions handled well before and after, the cost per answer when it moved, and each changed question with its answers before and after; a change the repeat answers did not confirm waits under **Not confirmed yet**, marked only possibly fixed or possibly broken. A bar is green or red only for a change confirmed by asking again; otherwise it stays grey, and a difference of one question, or bars pointing in opposite directions, is called within noise. Under **Show details** in the row: **How we measured it**, one sentence saying how many questions the helper saw and how many were kept aside to decide the result; **Which change helped?** when the attempt made two changes or more, with what testing each on its own costs; and, only when the session has a draft to test, **Check whether the draft would help**, as if search found it or through real search. When the checks were noise - answers graded both ways when asked again within an attempt, or today's version scoring differently between attempts on the held-out questions they shared - and no attempt was better, the card says first that the test cannot tell a better version from a worse one, offers what makes it reliable - yes-or-no grading criteria instead of a scale, a rule for length and format instead of the judge, more questions up to about 30 kept aside, a stronger judge model - and lists the questions graded both ways with each attempt's grades. Beside a better attempt it only notes the noise. Attempts that shared fewer than five held-out questions are not compared for noise, and the card says so. Two attempts in a row that changed nothing, or could not be graded reliably, earn a hint that another will probably not help; the session never stops on its own before its attempt limit, and the card names that limit only once it is reached. See [when the grading itself moves](evals.md#a-flip-is-confirmed-before-it-counts) and [how steady the answers are](evals.md#how-steady-the-answers-are).
5. **Accept.** Figures for what the new version fixes, breaks and costs per answer, and how many questions it was tested on. The topics this session found missing from the knowledge base are listed with their questions. A session drafts none of them: each offers **Draft** with the most one draft costs, says **Drafting…** while it is written, and once drafted offers **Review and add** or **Not now**, which sets it aside for the session (`PUT /{run_id}/topics/{topic_id}/later`). Each place people use the agent says whether it switches at once, after its automatic check passes or stays on its version. Then **Publish version N** or **Keep as draft**. Either ends the session, and this step then says what was decided, by whom and when, with a link to the version. With nothing to accept, the step is skipped.

A link to a step that no longer exists - `?step=testSet` or `?step=today` - opens the step that took its place, **Understand** or **Check**, without adding a history entry.

A failed proposal or eval can be retried explicitly with `/{run_id}/retry`; repeated clicks do not create another child. Automatic job retries never repeat a paid call. Human decisions update the session to accepted, published or rejected. The confirmed `/{run_id}/finish` action accepts the selected checked changes, in a wording of your own where you gave one, and optionally publishes in the same transaction.

A session kept as a draft is finished: publish the draft with the agent's own **Publish**, and when that version is the one the session measured, it is recorded on the session. Finishing can set up a publish-triggered suite with zero allowed regressions. Normal permissions and publish validation still apply, and guarded environments wait for their checks. Changes edited after their test must be tested again.

The session estimate includes sorting bad chat answers against writable knowledge bases bound to the agent and grouping their misses into [topics](knowledge-gaps.md#topics). It includes no drafts: a draft is written only when a person asks for one, and is paid as that run. Each step checks its complete estimate again before starting. Only frozen, unerased source chats reach classification or grouping; training failures remain agent evidence, and held-out text never reaches these helpers.

A failed classifier is shown explicitly, leaves the source conversations available, and the session still stops at **Understand**. A session needing only knowledge stops and lists the topics missing from the knowledge base, to draft the ones you want, without creating an empty agent version. A draft goes stale once a document is added to the knowledge base after it was written, and **Redraft** writes it again (see [Drafting the missing content](knowledge-gaps.md#drafting-the-missing-content)). Checking a draft still requires its own estimate and confirmation; adding content remains a separate human decision.

A human review decision and its withdrawal recompute the current measured attempt in the same transaction as the test and suite results. The selected attempt and its spend remain unchanged. Earlier measurements and individual-change checks cannot replace the current combined verdict. No new model call, publication or environment move follows a review. If the original requester can no longer read the comparison, the cached attempt becomes inconclusive instead of retaining a green verdict. Live dataset events refresh the test, suite, session and environment views.

The step bar distinguishes completed work, running work, steps needing your decision, skipped work and steps not started. Select any step to inspect it; this does not start a paid action. Reopening a session shows its current work, while the bar keeps each step’s recorded state. On a phone the current step and its status appear below the markers.

**Raise the limit and continue** appears where a priced step did not fit. A fresh complete estimate and confirmation come before more spending; the sources, pinned questions and attempt cap remain unchanged. Retrying a failed step stays in the same attempt. A resumed test reserves only its remaining measurements, including any remaining inconclusive repeat.

**End without changes** on the result, **Discard** on other steps, confirms dismissing only this session’s pending proposals. It leaves other batches alone and refuses to undo an applied change. Quotes announce no write; confirmed decisions refresh open agent pages.

#### Improvement history { #improvement-history }

The agent's **History** tab lists its improvement sessions, newest first: when each started and who started it, how its chosen attempt measured, what was decided and what it cost.

A finished session - kept as a draft, published, discarded, cancelled, or closed because its starting point changed or nobody took it further for seven days - opens its wizard to be read: every step and its details can be opened, and nothing can be changed or paid for. Its last step says what was decided, by whom and when, lists the changes it measured as they were decided, says what became of each knowledge document it drafted and whether an automatic check guards the agent.

A session waiting for you, at its result, stopped or failed is still open: **Improve** and its entry in the history take you back to it, to take its next step, raise its limit and continue, choose an attempt, retry the failed step or discard it.

The API answers any change to a finished session with `409`, except repeating the cancel or discard that ended it. `GET /{run_id}/changes` reads the changes its chosen attempt measured. Reading a session needs read access to the agent and `runs:view`; changing or starting one also needs edit access to the agent.

#### Asking the Architect { #asking-the-architect }

The [Architect](console.md#the-assistant) reads an agent's sessions, test runs and
test questions, and explains a result in plain words: what an attempt fixed and
broke, whether a change was confirmed by asking again, and how the held-out
questions moved. It links the wizard rather than retelling it.

At each stop it says what the session found, what the next step does and what it
costs. It starts a session, runs its next step, tries again, chooses an attempt,
accepts, publishes or ends a session only when you ask; a session it started can
be continued in the wizard, and the other way round.

Asked what to do, it recommends one step and asks first. Every change it makes
waits for your approval on a card, after one sentence saying what and why;
starting shows what the analysis costs and the spending limit for the whole
session, and every later step shows its own price. It calls the wizard's own
actions as you, so the same checks apply: a changed agent refuses the
acceptance, a guarded environment waits for its check, and the audit log records
you, with the Architect's credential named beside you.

### Proposing a new skill { #proposing-a-new-skill }

The assistant can propose **Worth creating a skill** when a reusable procedure appears in at least three distinct evidence answers. Each supporting passage must occur in the answer itself; reader comments alone do not establish a repeated procedure. The card shows its name, description, full body, rationale and verified evidence. A check binds a temporary skill to the candidate only: no skill row or published version is created.

**Accept** creates the private skill and binds it to the agent's draft in the same transaction. It requires `skills:edit` as well as edit access to the agent. Without creation permission the proposal remains readable and testable, but Accept explains why it is disabled. **Dismiss** creates nothing. **Undo** removes the binding and keeps the independent skill; accepting again reuses it only while its name and body still match. Skills contain written know-how and grant no tools. Additional tool access needs separate policy-checked proposals, with writing tools requiring approval.

A procedure drawn from fewer than three distinct answers is not proposed as a suggestion. It waits in **To review**, under New skills, with its full text. **Dismiss** moves it to **Decided**, and Undo brings it back. **Create skill** opens a preview: the name, description and body can be edited, and a warning says how many answers it is based on. **Create skill** in the preview creates the skill in the library and binds it to the agent's draft, never to a published version. It needs the same permissions as Accept and makes no model call. A second click returns the skill already created.

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


The Accept screen names the next version and repeats the selected round’s measured result. The automatic-check offer appears only when the agent has no suite. Publishing records the version identity and number on the session, so reopening Done links to that publication even after a later publish. Old sessions without this pin show their stored state without guessing a version. A failed suggestions read offers a retry; replaced suggestions are unavailable rather than indefinitely loading. Guarded followers wait for their checks and pinned environments stay on their current version.
