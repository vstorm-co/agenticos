---
title: "Knowledge gaps"
description: "Knowledge gaps show the questions an agent searched its knowledge base for and found nothing relevant, or answered without knowing, grouped by topic, so you know which document to add."
---

# Knowledge gaps

Many bad answers are not a problem with the agent's instructions. The
knowledge base does not contain the answer, and no change to the prompt fixes
that. **Knowledge gaps** show those questions: the ones an agent searched its
[knowledge base](file-processing.md) for and found nothing relevant to, or
answered without knowing, grouped by topic, with how often each was asked and
by which agents.

A gap tells you what is missing. It never adds anything to a knowledge base by
itself. A person writes the missing content in the topic - a model can draft it
- and adds it to the knowledge base as a document, and can first turn the
topic's questions into [dataset](datasets.md) cases, so an eval can show
whether the new document changed the answers.

## How a question becomes a gap { #how-a-question-becomes-a-gap }

Every time an agent searches its knowledge base during a run, the platform
records the search: the query the agent sent, the knowledge bases it searched,
how many passages came back, and how similar the closest passage was to the
query. A search is a **miss** when it returned nothing, or when its closest
passage is less similar to the query than `KNOWLEDGE_GAP_MIN_SIMILARITY`.

| Setting | Default | What it decides |
|---|---|---|
| `KNOWLEDGE_GAP_MIN_SIMILARITY` | `0.30` | The cosine similarity below which the closest passage counts as "nothing relevant". What a good match scores depends on the embedding model, so check a few of your own searches before you change it |

The similarity is the cosine similarity of the passage's vector to the query's
vector. It is not the ranking score: with hybrid search or query expansion the
ranking score is a fused rank and says nothing about how close a passage was.

Every search is kept, not only the misses. When you change the threshold, it
applies to the searches already made: the gaps you read are always the
searches that fall below the current setting.

Only searches an agent makes while it runs are recorded, and only for
questions people asked: a search through the HTTP API's `/rag/search`, a
preview on the knowledge base's page, a search made by an eval run, and one
made by a builder testing a draft are not. The first 1,000 characters of a
query are kept.

## Answers and comments { #answers-and-comments }

A search can find a passage and the agent still not know the answer, and a
reader can rate an answer down because something was missing. Retrieval alone
sees neither. **Check N answers**, on the knowledge base's Knowledge gaps tab,
asks a model to read the knowledge base's recent answers for them. It is
offered while [AI assistance](governance.md#ai-assistance) is on, and counts
the answers not read yet. While the switch is off, the tab says how many
answers wait, with a link to the switch for whoever may change it.

The model is the **Knowledge gap classifier**, a
[system agent](concepts.md#system-agents) every organization has. It reads each
answer with its question, the comments of anyone who rated it down, and the
instructions and [context files](context.md) of the agent version that gave it -
those the person who asked for the check may read - and decides one of four
things, with one sentence on why:

| Verdict | When |
|---|---|
| The agent did not know | The answer says, in any words or language, that the agent did not know or could not find the information. A fair question the agent turned down because it had nothing on it is this, not a refusal |
| Information was missing | A thumbs-down comment says information was missing, outdated or incomplete |
| Rightly refused | The question asked for what the agent's rules or purpose do not allow - to ignore its instructions, grant an exception, or help with something it is not for - and the agent refused. Not a gap, and the run's searches that missed stop counting as gaps too - in that knowledge base, and in another one a missed search also covered, since a refusal is about the request, not about one knowledge base |
| No gap | Anything else: a correct answer, a refusal of something the rules allow, a comment about tone, length or a mistake. An answer that applied a policy or a rule wrongly is no gap: the rule was there, and that is a mistake to fix - and so is one whose agent's instructions or context files state what it needed. A comment that the information was outdated is a gap |

An answer of either of the first two becomes a question in the knowledge base's
topics, grouped like a search that missed. In the topic it says which of the
two it is, instead of naming a search.

An answer is read when its run, in the last 30 days, finished and either
searched the knowledge base or ran on an agent version bound to it, rated or
not: an answer in which the agent did not know is often rated by nobody. A run
whose search already missed
is read too, so that a rightful refusal takes its miss out of the gaps;
otherwise it is still counted once, as that miss. Runs over the HTTP API keep no answer, and eval
runs, whose questions are replayed or generated, are never read. Nor are a
builder's tests of a draft, delegated runs, or runs whose starter's account is
gone.

A check belongs to one knowledge base: what it finds is a gap of that base
alone. An answer whose run searched two knowledge bases is read again when the
other one is checked.

A check reads up to 100 answers, 20 to a run of the classifier. Each run is
checked against the classifier's budget and the organization's before the model
is called, and is listed in Activity under the person who asked: choose
**Every surface, evals included** to see it. Every answer read is remembered,
whatever the verdict, so none is paid for twice. One read as no gap is read
again only after a new thumbs-down with a comment. A check stops at a run that
ends without an answer, such as one a spent budget refuses, and keeps what it
read.

One check of a knowledge base runs at a time, as a background job on Admin ->
Background jobs: a worker that stops under it leaves the job ended there, never
lost without a trace, and what it read stays read.

An improvement session - [Improve](authoring.md) run in the background - reads
the bad answers it found the same way, those answers alone and whatever their age, and sorts each by its
verdicts: missing knowledge where a knowledge base was missing content, no
problem to fix where the agent rightly refused, and the agent's fault
otherwise. The answers missing knowledge leave what the improver reads, and
the session drafts their topics instead - only a topic at least two different
people asked about, three at most a round. An eval's runs are never read, so
no held-out case is.

## Topics { #topics }

Misses are grouped into **topics** by the meaning of the query. Every 15
minutes a background pass takes each knowledge base's new misses, embeds them
with that knowledge base's own embedding model, and puts each in the closest topic
of that knowledge base, or starts a new one. A pass embeds at most 500 misses
per knowledge base; the rest wait for the next one. A knowledge base with no
new misses costs no embedding call.

A miss joins the closest topic only when it is at least as similar to it as
`KNOWLEDGE_GAP_TOPIC_SIMILARITY`; otherwise it starts a new one.

| Setting | Default | What it decides |
|---|---|---|
| `KNOWLEDGE_GAP_TOPIC_SIMILARITY` | `0.55` | The cosine similarity a miss needs to a topic to join it. What questions about one subject score depends on the embedding model: about 0.5 to 0.7 on OpenAI's `text-embedding-3` models. Raise it if unrelated questions share topics, lower it if one subject keeps starting new ones. The default is tuned for those models; an embedding model served behind an OpenAI-compatible endpoint, such as bge or e5, scores even unrelated questions high, so raise it there |

- A search over two knowledge bases becomes a question in a topic of each.
- A knowledge base moved to another embedding model starts new topics, because
  vectors from two models cannot be compared.
- A topic keeps its identity as questions are added to it, so a decision you
  made about it still applies.

**Group now** on the knowledge base's Knowledge gaps tab runs the pass for that
knowledge base at once, instead of waiting for the schedule. Until a question
has been placed in a topic, the tab counts it as not grouped yet.

## Reading gaps { #reading-gaps }

Gaps are shown in three places:

- the **Knowledge gaps** tab of a knowledge base: every topic of that
  knowledge base;
- the **Knowledge gaps** tab of an agent: only the questions that agent asked,
  in the knowledge bases you can read;
- the **Knowledge gaps** dashboard widget, added from **Customize**: the most
  asked topics across the organization, and how many topics each knowledge
  base holds.

A topic belongs to its knowledge base, so who reads it follows who reads that
knowledge base. There is no separate filter by department: a department sees
the gaps of the knowledge bases shared with it.

A topic shows how many times it was asked and by how many people, when it was
last asked, which agents asked it, and up to three of its questions. People
who asked through a channel count by their chat account; everybody who asked
anonymously, through a widget or with no person behind the run, counts as one. Open it to see the most
recent questions: what the person asked, what the agent searched for, how
close the closest passage was, and the comment of anyone who rated the answer
down. A question read from an answer says whether the agent did not know or a
reader said information was missing.

## Acting on a gap { #acting-on-a-gap }

An open topic has an editor: a title and the content in Markdown, empty or
filled with the topic's draft. **Add to dataset** and **Dismiss** are in a
topic's **…** menu, on its row and in the topic itself.

| Action | What it does |
|---|---|
| **Add to** *knowledge base* | Adds the title and content to the topic's knowledge base as a Markdown document, through the same path as an upload, and marks the topic **covered** by it. Refused while a detail is still to fill in, or while something may identify a person and you have not confirmed it (see [Personal data](#personal-data)) |
| **Save** | Keeps the title and content on the topic without adding them anywhere |
| **Add to dataset** | Turns the topic's most recent questions (up to 200) into cases of a dataset you may change, as one new version. Each case is the person's question, with the agent's answer as the counter-example. A question asked over the HTTP API keeps no answer and is skipped |
| **Dismiss** | Marks a topic as needing no content. A dismissed topic keeps the questions that belong to it, so it does not come back as a new topic. **Reopen** reverses it |

A covered topic says which document covers it, keeps the questions that belong
to it like a dismissed one, and is listed under **Covered**. If that document is
deleted, or fails to ingest, the topic is open again; a dismissed topic is
reopened before content is written for it. **Reopen** on a covered topic leaves the
document in the knowledge base. The document records the topic it was added
from and who added it, and each addition is in the audit log as
`knowledge_gap.content_added`.

You can also upload a document yourself, or add it to a source the knowledge
base syncs from. After you add the content, run an eval over the dataset. The
cases that failed because the knowledge was missing should now pass.

## Drafting the missing content { #drafting-the-missing-content }

**Draft the missing content**, in an open topic, asks a model to write the
passage or FAQ entry the knowledge base is missing. It is one run of the
**Knowledge gap drafter**, a [system agent](concepts.md#system-agents) every
organization has. The drafter is shown the topic's 20 newest questions: what
each person asked, what the agent searched for and found, the answer the
person got, and any comment left with a thumbs-down. What identifies people is
taken out first (see [Personal data](#personal-data)); from what the search
found, the knowledge base's own text, only personal data is, so its figures
stay. It is also shown the
[context files](context.md) the topic's agents read in their published
versions, those you may read, so the draft follows the rules the agents
already follow.

The draft fills the topic's editor, with a link to its run. You can copy it or
download it as Markdown, and it reaches the knowledge base only when somebody
adds it. The drafter does not know your company's facts: where an answer needs
a number, a date or a rule, it writes `{{what to fill in}}`, and the editor
lists each one until it is replaced.

When a context file or a document already
answers the questions, the drafter says so, and the topic names that source:
dismiss the topic instead of adding content. Drafting again replaces the
draft. Whoever may edit the drafter finds **Edit the drafter's instructions** on
the draft, and the drafter itself under **System agents** on the Agents page.

A draft names its sources: the documents of the knowledge base it builds on,
the context files it follows, and the topic's questions it answers. Each one is
verified before the draft is kept - a document must belong to the topic's
knowledge base, a question must be one of the topic's, a context file one you
may read - and one that is not is left out, never shown, and counted on the
draft. At most 12 sources are kept. A source deleted later is no longer shown.

Change a draft in the editor and it is your content: its run and its sources
are no longer shown, since what the model cited no longer speaks for it.

A draft is a model run like any other. It is refused while the organization
has [AI assistance](governance.md#ai-assistance) switched off, which it is
until someone with `org:settings` turns it on; until then the topic says so,
with a link to the switch for whoever may change it. It is checked
against the drafter's budget and the organization's before the model is
called, and its cost is listed in Activity. Grouping questions into topics
asks no model to write anything, so it runs whatever the switch says.

## Access { #access }

A topic is made of people's questions, so reading gaps needs `runs:view`, the
permission that reads every run in the organization in Activity. A member
without it does not see the tab or the widget, and the API refuses them.

| To | You need |
|---|---|
| Read a knowledge base's gaps | `runs:view` and `collections:view` on that knowledge base |
| Read an agent's gaps | `runs:view` and `agents:view` on the agent; topics of knowledge bases you cannot read are left out |
| Dismiss, reopen or regroup | `runs:view` and `collections:edit` on the knowledge base, from your role or an edit grant on it |
| Add a topic to a dataset | `runs:view` and `datasets:edit` on the dataset |
| Draft the missing content | `runs:view`, `collections:edit` on the knowledge base, and `agents:run` on the Knowledge gap drafter |
| Write, save or add a topic's content | `runs:view` and `collections:edit` on the knowledge base, from your role or an edit grant on it |
| Check answers | `runs:view`, `collections:edit` on the knowledge base, and `agents:run` on the Knowledge gap classifier |

A check of answers runs later on your role, so it is started only in person:
not through an API key, and not while an administrator impersonates you.

A knowledge base, agent, topic or dataset you may not reach answers "not found",
and so does one in another organization. See [Permissions](permissions.md).

## Personal data { #personal-data }

A recorded search is user content: the agent phrased it from what somebody
asked. It is deleted with the run it was made in, and with the conversation
it came from. Deleting a person deletes the searches made while answering
them, including those in runs with no conversation. Their export includes
them.

Every search is kept, a hit as well as a miss, so a changed threshold applies
to the searches already made. None outlives its run: the runs class of
[retention](governance.md#retention) deletes them with it.

A topic copies no question. Its name, its examples and its count are read from
the searches it still holds, so when those searches are deleted the topic has
nothing left, and the next grouping pass removes it, with its draft.

A draft is the one text a topic keeps, written by a model or a person. Credentials in it
are redacted before it is stored. Drafting sends the questions, answers and
comments to the drafter's model provider, with what identifies people taken out
first: e-mail addresses, phone, card and bank account numbers, and every number
or code of four digits or more, or three with a letter, such as an order number.
A figure like "30 days" or "$500" stays. Nothing a person writes is changed. See
[Data protection](data-protection.md#where-personal-data-lives).

Erasing a person removes the drafts a model wrote from their questions.
Content a person wrote or changed stays, and so does a document added from it.

A document added from a topic reaches everybody its knowledge base's agents
answer, so before it is added the content is checked for personal data and for
any such number or code it repeats from the topic's questions, answers or
comments, unless a context file of the topic's agents states it too. What is
found is shown in the topic, and adding waits until you confirm it. The audit
entry records how much was flagged and that it was confirmed, not what. The
document stays when the topic, the person who added it or a person whose
question shaped it is deleted: a person checked and confirmed what it says.

A question read from an answer is kept the same way as a search: it holds the
person's question and goes with its run and its conversation. Checking answers
sends questions, answers and thumbs-down comments to the classifier's model
provider. What is remembered of every answer read is its verdict, the
classifier's run and its one-sentence reason, which goes with the answer.

## What gaps do not detect yet { #limits }

Answers are read only when somebody checks them, and only from the last 30
days. Runs over the HTTP API keep no answer, so a question asked there becomes
a gap only when its search missed. An answer rated down without a comment is
read for what the agent said, not for the rating.

Names are not taken out of what the drafter reads, nor flagged in content to
add: nothing here recognises a name. Check a draft for them before you add it.
