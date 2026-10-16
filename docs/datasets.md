---
title: "Datasets"
description: "Datasets hold the questions an agent is tested on, as versioned cases written by hand, imported from CSV or JSONL, or taken from a rated answer."
---

# Datasets

A **dataset** holds the questions an agent is tested on. Without one, every
check of "did this change make the agent better" is somebody trying a few
prompts by hand and remembering how the last answer looked.

Each question is a **case**: the message the agent answers, and what a good
answer looks like. Cases come from three places - written in the console,
imported from a file, or taken from a real conversation where somebody rated
the answer down. The last is usually the most useful, because it is a question
a person actually asked and an answer that actually disappointed them.

## What a case holds

| Field | What it is |
|---|---|
| Input | The message the agent answers |
| Conversation before the input | Optional earlier turns, oldest first. With them, the case is a conversation prefix and the agent answers its last turn |
| Reference answer | What a good answer says |
| Counter-example | An answer known to be wrong |
| Expected tool calls | The tools the agent should call, each with the arguments that must match. Arguments a case does not list are ignored. A case also says how the calls are matched: `any` order, `in_order` with other calls allowed between them, or `exact` - these calls, in this order, and no others |
| Checks | Rules about the answer, each an object whose `type` names the rule, with that rule's parameters beside it. [Grading](#checks) lists the types, and a case with a type it does not know is refused |
| Tags | Labels for grouping results, such as `billing` or `refusal` |
| Note | Why the case exists - what went wrong, or what it guards |
| Source | `manual`, `import`, `conversation` or `synthetic` - set by the platform, not typed |

A case has to say what its answer is tested against: a reference answer, a
counter-example, an expected tool call or a check - at least one of the four. A
case with only an input could never fail, so it is refused: the form will not
save it, the API answers 422 naming `reference_answer`, and an import names the
row.

A good case is small: one question, and the one thing a right answer has to get
right. A reference answer or a counter-example is usually enough. Add expected
tool calls when the agent has to act rather than answer, checks when a rule can
be stated exactly, and the conversation before the input only when the question
depends on it. The note is for the next reader: what went wrong, or what the
case guards. Creating your first dataset in the console offers a guided walk
that ends on writing its first case field by field.

A case taken from a conversation also keeps a link to the run, the conversation
and the message it came from. The question and the answer are copied into the
case, so the case stays complete after the run itself is removed by retention.

Attachments are not part of a case in this version. A case is text.

## Every change is a new version { #versions }

Adding, editing or removing a case, and importing a file, each create a new
**version** of the dataset, numbered from 1. A version never changes after it is
created. An edited case is stored as a new revision, and the version before the
edit still holds the old one.

This matters when you compare results. Two eval runs over the same version saw
the same questions, so a difference in their results comes from the agent, not
from the test. The dataset page shows the newest version by default; choose an
older one from the version list to read it. An older version is read-only.

Renaming a dataset or changing its description, with **Edit details** on its
page, does not create a version, because neither changes a case.

The version list shows the newest hundred versions; an older one is opened by
typing its number. Every version keeps a row per case, so one organization's
versions together hold at most `DATASET_MAX_VERSION_ROWS_PER_ORG` rows (5
million by default, see [Configuration](configuration.md#datasets)). A change
past that is refused with how many are held; deleting a dataset frees its rows.

## Adding cases

### In the console

Open **Datasets**, create a dataset - it opens as soon as it exists - and choose
**Add case**. Write the input and at least one of the four expectations above.
The conversation is written turn by turn, each expected tool call as a tool name
and its arguments as name and value rows, and each check as a type picked from
the list beside what it checks. **Edit as JSON** shows the whole case in the shape
an import holds.

A case in the list opens as it reads, with the conversation as chat bubbles;
**Edit** turns it into the form, which says which version a save makes and which
of the dataset's scorers would grade the case as written. A link to
`?tab=cases&case={case_id}` on the dataset's page opens one case.

Saving a new case whose question a case already asks - compared without regard
to case or spacing - stops to say so, with **Open it** to read that case instead
and **Add anyway** to keep both. The check is `GET
/datasets/{id}/cases?same_input=`.

### From a file { #import-and-export }

**Import** reads a `.csv` or a `.jsonl` file and adds every case in it as one
new version. The import is all or nothing: if one row is invalid, no row is
added, and the refusal names each invalid row so you can fix the file and try
again. A file is at most 10 MB, and a dataset holds at most 10,000 cases.

Both formats use the same nine field names:

| Column | In CSV | In JSONL |
|---|---|---|
| `input` | Text. Required | String. Required |
| `history` | A JSON list in the cell, or empty | A list of `{"role", "content"}` objects |
| `reference_answer`, `counter_example`, `note` | Text, or empty | String or `null` |
| `expected_tool_calls` | A JSON list in the cell, or empty | A list of `{"tool", "args"}` objects |
| `order_mode` | `any`, `in_order` or `exact`; empty means `any` | String |
| `checks` | A JSON list in the cell, or empty | A list of check objects |
| `tags` | Comma-separated | A list of strings |

A CSV file must have a header row. Columns other than these nine are refused,
so a typo in a column name does not silently drop its data. Columns you leave
out take their empty value. Inside a check and inside a tool call's arguments, keys are exported in alphabetical order, after a check's `type`.

```csv
input,reference_answer,tags
How long is the return window?,30 days from delivery,returns
Can I return a used kettle?,"No, only unused items",returns
```

**Export** downloads the version on screen as CSV or JSONL. An export imports
back unchanged. To keep that true for a spreadsheet, a CSV cell that starts with
`=`, `+`, `-`, `@` or `'` is written with a `'` in front, so a spreadsheet does
not run it as a formula, and an import removes that one `'` again. Exporting is
recorded in the [audit log](governance.md#audit).

### From a conversation or a run { #add-to-dataset }

There are two ways in, and both make the same case:

- **In the chat**, rate the answer, and the rating decides what the answer is
  kept as. After a thumbs-up, the confirmation offers **Add to dataset**: choose
  the dataset and the answer is kept as the reference answer. After a
  thumbs-down, the dialog that asks what went wrong also offers **Add this
  answer to a dataset**: tick it, choose the dataset and submit, and the answer
  is kept as the counter-example. The rating is saved first and the case is
  added after it, so your comment becomes the case's note. They are two
  separate writes - if the add is refused, the rating stays, and the message
  says which half failed. Removing the rating later leaves the case where it
  is: it is a copy, versioned with its dataset. The console remembers the
  dataset you added to last, so the next add is one click.
- **In Activity**, every agent turn has an **Add to dataset** control. This is
  where answers are curated, so a good answer can be kept as a reference just
  as easily as a bad one as a counter-example. With no dataset to add to yet,
  it starts one, visible to the organization; opened from a dataset's **Add
  from Activity**, it adds to that dataset and offers the way back to it.

Either way, the case is created from the turn:

- the question becomes the input, and the turns before it become the
  conversation before the input;
- the answer becomes the counter-example. If nobody rated it down, it is
  offered as the reference answer instead, and you can choose either;
- the newest comment left with a thumbs-down becomes the note.

Both are shown only to members who may edit a dataset. The message must belong
to your organization, and you must be able to read it: either you hold
`runs:view`, which reads every run in the organization as Activity does, or you
can open the conversation. A message from another organization is refused as if
it did not exist, and an answer already a case of the dataset's newest version
is refused rather than added twice.

## Credentials are redacted { #credentials }

Case text is copied from conversations and from files people upload, and it is
later exported and given to models. Before a case is stored, the platform
replaces any API key or token it recognizes with a placeholder such as
`[redacted:github_token]`. This applies to every field a model reads or an
export carries, including the arguments of an expected tool call, and to every
way a case is added. The audit entry for the change records how many values
were redacted, never the values.

## Grading { #scoring }

A dataset says how its cases are graded, on its **Grading** tab, in three cards
saved together: **When a case passes** holds the checks and the expected tool
calls, **Judge** says which judge grades and on what, and **Review by a
person** says what waits for somebody's decision. Four scorers can apply to one
case, and each is switched on or off and marked **Must pass** or not:

| Scorer | What it compares | Costs |
|---|---|---|
| Checks | The answer against the case's rules, and against default rules the dataset gives every case | Nothing |
| Expected tool calls | The tools the agent called against the case's expected calls | Nothing |
| Judge | The answer against a rubric of named criteria, graded by the dataset's judge | A run of the judge |
| Reference answer | The answer against the case's reference answer, graded by the dataset's judge | The same run of the judge |

Each scorer returns pass or fail, a score from 0 to 1 and a reason. A case
**passes** when every scorer marked Must pass passes, and **fails** when one of
them fails. When one of them reached no verdict - the judge was switched off,
its budget was spent, its run failed or its answer could not be read - the case
is **not graded**: neither passed nor failed, because nobody checked the
answer. The score says why, and it can be [scored again](#judge) once the cause
is fixed.

Each scorer says how many cases hold what it reads, and the tab warns when the
setup on screen would grade some cases on nothing. A dataset whose cases have
reference answers that nothing compares answers with is offered the reference
comparison. A card with a change not yet saved says so, a bar at the bottom of
the screen saves or discards every change at once, and the page asks before it
is left.

The configuration is not versioned with the cases, because how a team grades is
not what it asks. Each score keeps a copy of the configuration it was computed
with, so an older score still says how it was reached after the configuration
changes.

A configuration that could score nothing is refused: every scorer off, or the
judge on with no criteria. So is a score of a case none of the configured
scorers has anything to check on - nothing is kept and the judge is not called.

### Checks { #checks }

| `type` | Parameters | Passes when |
|---|---|---|
| `contains`, `not_contains` | `value`, optional `path`, `case_sensitive` | The answer contains the value, or does not |
| `equals` | `value`, optional `path`, `case_sensitive` | The answer, trimmed, is the value |
| `regex` | `value` (at most 500 characters), optional `path`, `case_sensitive` | The pattern matches somewhere in the answer |
| `json_schema` | `schema`, optional `path` | The answer is JSON matching the JSON Schema |
| `max_cost_usd` | `value` | The run cost no more than this |
| `max_latency_ms` | `value` | The run took no longer than this |
| `judge` | `criterion` | The eval judge grades the criterion at or above the pass mark |

`path` reads into an answer that is JSON: `items.0.name` is the first item's
name. Without it, a rule reads the whole answer. Text rules are not case
sensitive unless `case_sensitive` is true.

A pattern is checked when the case is written, and a rule reads at most the
first 100,000 characters of an answer. A pattern that takes longer than a tenth
of a second on an answer stops and is recorded as an error, so one pattern
cannot hold up scoring. For the same reason a JSON Schema may not use `pattern`
or `patternProperties` - a `regex` check with a `path` does the same under the
deadline - and its `$ref` must point inside the schema.

A `judge` check is a criterion for one case only, graded in the same judge run
as the dataset's rubric. Use it for what a rule cannot express, such as "refuses
and does not reveal the customer's address".

### Expected tool calls { #trajectory }

The agent's calls are matched against the case's expected calls by tool name and
by every argument the case names. The case's order mode decides what passes:
with `any`, every expected call happened; with `in_order`, they happened in the
listed order; with `exact`, they are the only calls and in that order. The
reason names what was missing, what was not expected, or that the order was
different. A write that an isolated run blocked still counts as a call the
agent made.

A call is matched by the tool name the run recorded, which is the name after
any override in the spec. A case written before a tool was renamed expects the
old name.

### The judge { #judge }

A judge is an agent of the `judge` kind (see
[Judges](concepts.md#system-agents)). A dataset grades with the **Eval judge**
the platform adds to every organization, or with a judge of its own: **Create a
judge for this dataset**, on the Judge card, makes one whose prompt is the Eval
judge's, with its rules of grading, followed by the dataset's name and
description and what you say the judge must know to grade - a policy, a price
list - on the organization's first model or one you pick. The prompt is shown to
edit before it is created (`GET /datasets/{id}/judge-template`). Creating it
needs `agents:edit` as well as `datasets:edit`.

Where AI assistance is on, creating it switches grading on as well: the judge,
on a starting criterion to replace when the dataset has none, and the reference
comparison when a case has a reference answer. The criteria, the scale and the
pass mark stay on the dataset; the judge's prompt, model and budget are edited
on its own page, the one place its model is set; the Judge card shows it.

A judge runs as the person who asked for the score: their access to it is
checked, it is checked against its own budget and the organization's before the
model is called, and its run appears in Activity under the `eval` surface.

The judge is handed the case's note, as why the case exists, its earlier turns
and question, the reference answer when it is graded, the counter-example,
every tool call the agent made - its arguments, and whether an isolated run
blocked it - and the answer. A case with a counter-example is always graded on a
required **counter-example** criterion as well: the answer must not repeat the
known bad answer, and the judge is asked to quote what sets the answer apart
from it. A pass is an error when it quotes only what the two share, or when the
answer copies the counter-example; one with nothing quoted stands, marked
unverified.

Judges start at temperature 0, so one answer is graded the same way twice; a
model that takes no temperature, such as a reasoning model, grades without one.

The judge runs only where [AI assistance](governance.md#ai-assistance) is on,
and it is off until an admin turns it on for the organization. Until then the
judge's and the reference answer's criteria are recorded as skipped, only the
rule-based scorers score, and the Grading tab says so with a link to the switch
for whoever may change it. The judge and the reference comparison cannot be
turned on meanwhile; one already on stays on, and is skipped.

Each criterion is graded from 1 to the top of the scale and passes at the pass
mark or above. For every criterion the judge quotes the passage of the answer
its grade rests on and names the rule the grade follows from. A grade whose
reason is mostly the criterion's own words, with no quote the answer holds, is
an error: nothing shows the judge read the answer. A top grade with nothing
quoted from the answer stands, marked unverified.

When the judge cannot grade, its criteria are recorded as skipped or as errors,
with a reason that names the cause: AI assistance is switched off, the judge
the dataset picked no longer exists, it has no published version, it is
archived, its model is gone or has no key, the person may not run it, its
budget is spent, its run failed, or its answer could not be read, whose first
2,000 characters are kept beside the reason. The rule-based scorers still
score.

Once the cause is fixed, **Score again** on a result that was not graded - or on
every one in an eval run's group on the Review tab - grades the same answer
anew, with the configuration it was first graded with (`POST
/datasets/{id}/scores/rescore`, up to ten scores a request). The agent does not
run again, and the score keeps its eval run and any decision a person made on
it; one every scorer reached a verdict on is left as it is.

A cause still there - AI assistance off, the judge unpublished - is refused as it
stands, and so is an eval run's judge published anew since it failed, whose grade
would not compare with the rest of the run; nothing is graded then. An answer
graded on its own, from the chat or from Activity, has no run to compare with: it
is graded by the version published now, and its pin names that version.

A grade may quote the answer, up to 12 passages; a quote the answer does not
contain word for word is kept beside the grade as unverified, shown on its own
line under the reason, and the grade stands.

What backs a grade never sinks it: an empty or overlong quote is dropped,
quotes past twelve and a rule past 300 characters are cut, and only a missing
criterion id or grade makes a verdict unreadable. The judge's run in Activity
says which fields could not be read, never the answer, which can repeat a case
of a dataset its reader may not see.

Each score records the judge that graded it - the judge agent, its model
profile, its spec version, a hash of the rubric and the version of the task the
platform hands every judge - so scores from different judges are not compared as
like for like. Changing the judge, or its model on its page, is allowed;
switching the judge asks first, and the Judge card says that the scores graded
before will not compare with the ones graded after.

### Review { #review }

A score waits in the **review queue** when somebody sends it there, or an eval
run does. Once it has rerun what flipped, an eval run sends the regressions it
confirmed and the answers the judge failed on with an error - not one it
skipped, which waits to be scored again - one score per case, and none for a
case already waiting. Its page sends any others you pick, all at once through
`POST /datasets/{id}/scores/review` with up to 500 score ids - all of them or
none.

A score asked for by hand from Activity follows the dataset's **Review by a
person** setting: nothing until somebody sends one, every result that did not
pass, or every result. A score already decided stays decided.

The **Review** tab opens on what waits for a decision, with every result one click
away, each with its count, and narrows by outcome, by the agent that answered and
by a tag of the case. It puts each eval run's scores under one heading linking the
run, from which they can be taken out of the queue undecided
(`POST /datasets/{id}/scores/review/withdraw`).

Each card shows what the case asked and expected - the question, linked to the
case, the reference answer, the expected tool calls and the checks - the answer
as it was graded, which agent and version answered - with a warning when the
judge graded on the model that answered, since a judge may favour answers like
its own - what each scorer found and why, failing first, and the review
decision, which can be undone from the message confirming it.

The note left with a decision is often the rule the judge missed, so the card
offers to make it a judge criterion: for that case alone, as a `judge` check in
a new version of the dataset, or for every case, in the rubric, which switches
the judge on.

The **Waiting for review** dashboard card shows the queue across the datasets you
can see: how many results did not pass, were not graded or passed, and in which
datasets, each opening on its Review tab. The card is on the dashboard by default.

A person's review decision is stored beside the scorers' results and decides the
outcome. It never changes what the judge said: the judge's grades and reasons
stay on the score after it is overruled. A decision can be withdrawn, and the
score then waits for review again.

### Scoring a run { #scoring-a-run }

In **Activity**, open a run, open its **⋯** menu and choose **Score against a
case**. The case that asks the run's own question is picked for you; when the
dataset has none, the dialog offers to add the run's answer as a case. The run's
answer and tool calls are graded with every scorer the dataset configures. A run
with no transcript has no answer to grade.

| To | You need |
|---|---|
| Change how a dataset is graded | `datasets:edit` on it |
| Create a judge for it | `datasets:edit` on it, and `agents:edit` |
| Score a run against it | `datasets:run` on it, and `runs:view` |
| Read its scores | `datasets:view` on it |
| Send scores to review, record or withdraw a decision | `datasets:edit` on it |

A reason the judge wrote is passed through the same credential redaction as a
case before it is stored.

## Access { #access }

A dataset is a shared resource with an owner, a visibility and grants, like a
[skill](skills.md) or a [context file](context.md). A new dataset is visible to the
whole organization unless its creator starts it private; its page changes
that later. The catalog has three permissions for datasets:

| Permission | Lets a member | Grant level that gives it |
|---|---|---|
| `datasets:view` | Read a dataset's cases and versions, and export them | `read` |
| `datasets:edit` | Create datasets, change cases, import, delete, share | `edit` |
| `datasets:run` | Run evals over a dataset | `use` |

| | Owner | Admin | Builder | Operator | Member | Viewer |
|---|---|---|---|---|---|---|
| `datasets:view` | all | all | all | all | shared | shared |
| `datasets:edit` | all | all | shared | - | own | - |
| `datasets:run` | all | all | all | all | shared | - |

A member without access to a dataset gets "not found" for it on every route,
whatever their role allows elsewhere - whether a private dataset exists is
itself something they may not learn. A grant widens access to one dataset and
never changes a role. See [Permissions](permissions.md) for how scopes and
grants combine.

## Personal data { #personal-data }

A case taken from a conversation is a copy of what a person wrote and what the
agent answered. When the conversation is deleted, or the person who wrote it is
erased, the case stays and every link from it back to them is cleared: the run,
the conversation and the message it came from, and who added it if that was the
person erased. What stays is the text - which may still hold personal data
somebody typed into it, and is removed by deleting the case. See
[Data protection](data-protection.md#what-deletion-reaches).

A score is kept the same way. It holds a copy of the answer it graded, up to
8,000 characters with credentials redacted, so a reviewer reads it beside the
case. That copy comes back in the export of the person whose run it was, and is
cleared when that person is erased. When the run it scored is removed, the score
stays without the link to it, and when the person who asked for it or decided it
is erased, their name is cleared from it. A judge's reason may quote the answer
it graded.
