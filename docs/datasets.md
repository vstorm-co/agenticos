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
| Checks | Rules about the answer, each an object whose `type` names the rule, with that rule's parameters beside it. [Scoring](#checks) lists the types, and a case with a type it does not know is refused |
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

Open **Datasets**, create a dataset, and choose **Add case**. Write the input
and at least one of the four expectations above. The conversation, the expected tool calls and the checks
are written as JSON lists - the same text a CSV export holds them as.

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
  as easily as a bad one as a counter-example.

Either way, the case is created from the turn:

- the question becomes the input, and the turns before it become the
  conversation before the input;
- the answer becomes the counter-example. If nobody rated it down, it is
  offered as the reference answer instead, and you can choose either;
- the newest comment left with a thumbs-down becomes the note.

Both are shown only to members who may edit a dataset. The message must belong
to your organization, and you must be able to read it: either you hold
`runs:view`, which reads every run in the organization as Activity does, or you
can open the conversation. A message from another organization is refused as
if it did not exist.

## Credentials are redacted { #credentials }

Case text is copied from conversations and from files people upload, and it is
later exported and given to models. Before a case is stored, the platform
replaces any API key or token it recognizes with a placeholder such as
`[redacted:github_token]`. This applies to every field a model reads or an
export carries, including the arguments of an expected tool call, and to every
way a case is added. The audit entry for the change records how many values
were redacted, never the values.

## Scoring { #scoring }

A dataset says how its cases are scored, on its **Scoring** tab. Four scorers
can apply to one case, and each is switched on or off and marked required or
not:

| Scorer | What it compares | Costs |
|---|---|---|
| Checks | The answer against the case's rules, and against default rules the dataset gives every case | Nothing |
| Tool calls | The tools the agent called against the case's expected calls | Nothing |
| Judge | The answer against a rubric of named criteria, graded by the eval judge | A run of the judge |
| Reference answer | The answer against the case's reference answer, graded by the eval judge | The same run of the judge |

Each scorer returns pass or fail, a score from 0 to 1 and a reason. A case
**passes** when every required scorer passes. When a required scorer could not
run - the judge was switched off, its budget was spent - the case is
**unscored**, not passed: a result nobody checked is not counted as a pass.

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

### Tool calls { #trajectory }

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

The judge is the **Eval judge**, an agent the platform adds to every
organization (see [System agents](concepts.md#system-agents)). It runs as the
person who asked for the score: their access to it is checked, it is checked
against its own budget and the organization's before the model is called, and
its run appears in Activity under the `eval` surface. Its instructions can be
edited like any agent's, and a dataset can name another model for it.

The judge runs only where [AI assistance](governance.md#ai-assistance) is on,
and it is off until an admin turns it on for the organization. Until then the
judge's and the reference answer's criteria are recorded as skipped, only the
rule-based scorers score, and the Scoring tab says so with a link to the switch
for whoever may change it. The judge and the reference comparison cannot be
turned on meanwhile; one already on stays on, and is skipped.

Each criterion is graded from 1 to the top of the scale and passes at the pass
mark or above. When the judge cannot grade, its criteria are recorded as
skipped or as errors, with a reason that names the cause: AI assistance is
switched off, the judge has no published version, it is archived, its model
is gone or has no key, the person may not run it, or its budget is spent. The rule-based scorers still score.

A grade may quote the answer, up to 12 passages; a quote the answer does not
contain word for word is named in the reason as unverified, and the grade
stands. Each score records the judge that graded it - its model profile, its
spec version and a hash of the rubric - so scores from different judges are not
compared as like for like.

### Review and verdicts { #review }

A dataset can send results to a **review queue**: none until somebody sends one,
every result that did not pass, or every result. The Scores tab shows a
dataset's results, and the **Awaiting review** dashboard card shows the queue
across the datasets you can see: how many results did not pass, could not be
scored or passed, and in which datasets, each opening on its Scores tab. The
card is on the dashboard by default.

A person's verdict is stored beside the scorers' results and decides the
outcome. It never changes what the judge said: the judge's grades and reasons
stay on the score after it is overruled. A verdict can be withdrawn, and the
score then waits for review again.

### Scoring a run { #scoring-a-run }

In **Activity**, open a run and choose **Score against a case**. Pick the
dataset and the case, and the run's answer and tool calls are scored with every
scorer the dataset configures. A run with no transcript has no answer to score.

| To | You need |
|---|---|
| Change how a dataset is scored | `datasets:edit` on it |
| Score a run against it | `datasets:run` on it, and `runs:view` |
| Read its scores | `datasets:view` on it |
| Record or withdraw a verdict | `datasets:edit` on it |

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

A score is kept the same way. When the run it scored is removed, the score
stays without the link to it, and when the person who asked for it or decided
it is erased, their name is cleared from it. A judge's reason may quote the
answer it graded.
