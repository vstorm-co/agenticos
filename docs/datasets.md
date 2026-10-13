---
title: "Datasets"
description: "Datasets hold the questions an agent is tested on, as versioned cases written by hand, imported from CSV or JSONL, or taken from a rated answer."
---

# Datasets

A **dataset** holds the questions an agent is tested on. Without one, every
check of "did this change make the agent better" is somebody trying a few
prompts by hand and remembering how the last answer looked.

Each question is a **case**: the message the agent answers, and what a good
answer looks like. Cases come from four places - written in the console,
imported from a file, taken from a real conversation where somebody rated
the answer down, or drafted by the case generator and accepted by a person. The last is usually the most useful, because it is a question
a person actually asked and an answer that actually disappointed them.

## What a case holds

| Field | What it is |
|---|---|
| Input | The message the agent answers |
| Conversation before the input | Optional earlier turns, oldest first. With them, the case is a conversation prefix and the agent answers its last turn |
| Reference answer | What a good answer says |
| Counter-example | An answer known to be wrong |
| Expected tool calls | The tools the agent should call, each with the arguments that must match. Arguments a case does not list are ignored. A case also says how the calls are matched: `any` order, `in_order` with other calls allowed between them, or `exact` - these calls, in this order, and no others |
| Checks | Rules about the answer, each an object whose `type` names the rule, with that rule's parameters beside it. A case keeps them; scoring reads them and decides which types exist |
| Tags | Labels for grouping results, such as `billing` or `refusal` |
| Note | Why the case exists - what went wrong, or what it guards |
| Source | `manual`, `import`, `conversation` or `synthetic` - set by the platform, not typed |

A case taken from a conversation also keeps a link to the run, the conversation
and the message it came from. The question and the answer are copied into the
case, so the case stays complete after the run itself is removed by retention.

Attachments are not part of a case in this version. A case is text.

## Every change is a new version { #versions }

Adding, editing or removing a case, importing a file, and accepting generated
cases each create a new **version** of the dataset, numbered from 1. A version never changes after it is
created. An edited case is stored as a new revision, and the version before the
edit still holds the old one.

This matters when you compare results. Two eval runs over the same version saw
the same questions, so a difference in their results comes from the agent, not
from the test. The dataset page shows the newest version by default; choose an
older one from the version list to read it. An older version is read-only.

Renaming a dataset or changing its description does not create a version,
because neither changes a case.

## Adding cases

### In the console

Open **Datasets**, create a dataset, and choose **Add case**. The input is the
only required field. The conversation, the expected tool calls and the checks
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

Every agent answer in the chat, and every agent turn in **Activity**, has an
**Add to dataset** control. Choose a dataset and the case is created from the
turn:

- the question becomes the input, and the turns before it become the
  conversation before the input;
- the answer becomes the counter-example. If nobody rated it down, it is
  offered as the reference answer instead, and you can choose either;
- the newest comment left with a thumbs-down becomes the note.

The control is shown to members who may edit a dataset. The message must belong
to your organization, and you must be able to read it: either you hold
`runs:view`, which reads every run in the organization as Activity does, or you
can open the conversation. A message from another organization is refused as
if it did not exist.

### Generated by the case generator { #generating-cases }

Writing a hundred good cases by hand is why most teams have none. **Generate
cases** on a dataset's page asks the case generator to draft them, and you
decide which ones the dataset keeps. Choose the agent the cases test, the
sources to draft from, and how many cases you want - at most 50, shared evenly
across the sources:

| Source | What the generator drafts | What it is shown |
|---|---|---|
| From the agent | Typical requests and edge cases, with the tool calls a good answer makes | The agent's instructions, its skills and its tools, under the names the agent gives them |
| From knowledge | Questions its knowledge base answers. Each case links to the document its passage came from, keeps the passage as the reference answer, expects a call to the agent's knowledge search, and carries a `judge` check that the answer agrees with the passage | Passages from up to 12 indexed documents of the knowledge bases the agent uses and you can read |
| From conversations | Paraphrases and harder variants of what people asked the agent, rated-down answers first. Each case links to the question it varies | Up to 60 questions people asked the agent in this organization, with the comment left on a rated-down answer |
| Red team | Out-of-scope requests, prompt injections, attempts to extract personal data and attempts to get around the agent's policies. Each case is tagged `red-team` and `red-team:<category>` and carries a `judge` check that the agent refuses | The agent's instructions, skills and tools |

**The estimated cost comes first.** The dialog shows how many cases each source
will be asked for, how much each has to draft from, and an estimate of the
cost, before anything is spent. It is an estimate: the generator's budget is
checked when it runs, as any agent's is. Changing the agent, the sources or the
count throws the estimate away.

**Nothing reaches the dataset until you accept it.** The drafts wait under
**Proposed cases** on the dataset's page. Accept one as it is, edit it first, or
dismiss it, one at a time or a page at a time. One Accept is one new version,
whatever it carried, and its cases have the source `synthetic`. A dismissed
draft is deleted and leaves nothing in the dataset. An accepted one is deleted
from the drafts too: the version is the record of it.

**The generator is an agent.** It is a system agent seeded in every
organization, so its runs are metered against its own budget and the
organization's, and each generation is one run you can open in
[Activity](console.md). It has no tools: everything it reads is gathered for it
under your own access and handed over in its prompt, so a document or a
conversation that tries to instruct it can at most change the text of a draft
you review. A draft that does not keep its source's rule - a knowledge case
citing no passage it was shown, a conversation case varying no question it was
shown, a red-team case with no category - is dropped before you see it.

**Each source has its own gate**, and a source you may not use is refused by
name rather than left out quietly:

- every generation needs `datasets:edit` on the dataset, `agents:view` on the
  agent the cases test, and `agents:run` on the case generator, because it spends
  the organization's money;
- knowledge reads only the knowledge bases you may read; the dialog says how
  many the agent uses that were left out;
- conversations need `runs:view`, the permission Activity reads every run with;
- an organization that has switched AI assistance off cannot start a
  generation. Drafts already waiting can still be accepted or dismissed, because
  deciding them calls no model.

Only members who may edit the dataset see its drafts. A draft taken from a
conversation is text the dataset's other readers have not been shown; once it is
accepted, it is a case like any other.

## Credentials are redacted { #credentials }

Case text is copied from conversations and from files people upload, and it is
later exported and given to models. Before a case is stored, the platform
replaces any API key or token it recognizes with a placeholder such as
`[redacted:github_token]`. This applies to every field a model reads or an
export carries, including the arguments of an expected tool call, and to every
way a case is added. A generation also redacts the questions and passages it
hands the generator, before they leave for the model. The audit entry for the
change records how many values were redacted, never the values.

## Access { #access }

A dataset is a shared resource with an owner, a visibility and grants, like a
[skill](skills.md) or a [context file](context.md). A new dataset is private to
its creator until it is shared from its page. The catalog has three
permissions for datasets:

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

A generated case that is still waiting for a decision is not kept that way.
When the conversation it was drafted from is deleted, or the person who asked
the question is erased, the draft is deleted with it: nobody chose to keep it.
Generating from conversations sends the questions people asked, redacted, to
the case generator's model provider, and generating from knowledge sends
passages of the documents - see
[what leaves the deployment](data-protection.md#what-leaves-the-deployment).
