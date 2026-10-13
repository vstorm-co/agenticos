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
| Checks | Rules about the answer, each an object whose `type` names the rule, with that rule's parameters beside it. A case keeps them; scoring reads them and decides which types exist |
| Tags | Labels for grouping results, such as `billing` or `refusal` |
| Note | Why the case exists - what went wrong, or what it guards |
| Source | `manual`, `import`, `conversation` or `synthetic` - set by the platform, not typed |

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

## Credentials are redacted { #credentials }

Case text is copied from conversations and from files people upload, and it is
later exported and given to models. Before a case is stored, the platform
replaces any API key or token it recognizes with a placeholder such as
`[redacted:github_token]`. This applies to every field a model reads or an
export carries, including the arguments of an expected tool call, and to every
way a case is added. The audit entry for the change records how many values
were redacted, never the values.

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
