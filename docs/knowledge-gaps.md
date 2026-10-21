---
title: "Knowledge gaps"
description: "Knowledge gaps show the questions an agent searched its knowledge base for and found nothing relevant, grouped by topic, so you know which document to add."
---

# Knowledge gaps

Many bad answers are not a problem with the agent's instructions. The
knowledge base does not contain the answer, and no change to the prompt fixes
that. **Knowledge gaps** show those questions: the ones an agent searched its
[knowledge base](file-processing.md) for and found nothing relevant to,
grouped by topic, with how often each was asked and by which agents.

A gap tells you what is missing. It never adds anything to a knowledge base by
itself. A person writes or finds the missing document - a model can draft it -
and adds it, and can first turn the topic's questions into
[dataset](datasets.md) cases, so an eval can show whether the new document
changed the answers.

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
preview on the knowledge base's page, and a search made by an eval run are not. The
first 1,000 characters of a query are kept.

## Topics { #topics }

Misses are grouped into **topics** by the meaning of the query. Every 15
minutes a background pass takes each knowledge base's new misses, embeds them
with that knowledge base's own embedding model, and puts each in the closest topic
of that knowledge base, or starts a new one. A pass embeds at most 500 misses
per knowledge base; the rest wait for the next one. A knowledge base with no
new misses costs no embedding call.

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

A topic shows how many times it was asked, when it was last asked, which
agents asked it, and up to three of its questions. Open it to see the most
recent questions: what the person asked, what the agent searched for, how
close the closest passage was, and the comment of anyone who rated the answer
down.

## Acting on a gap { #acting-on-a-gap }

**Add to dataset** and **Dismiss** are in a topic's **…** menu, on its row and
in the topic itself.

| Action | What it does |
|---|---|
| Add the missing document | Upload it to the knowledge base, or to a source the knowledge base syncs from. Nothing is added for you |
| **Add to dataset** | Turns the topic's most recent questions (up to 200) into cases of a dataset you may change, as one new version. Each case is the person's question, with the agent's answer as the counter-example. A question asked over the HTTP API keeps no answer and is skipped |
| **Dismiss** | Marks a topic as needing no content. A dismissed topic keeps the questions that belong to it, so it does not come back as a new topic. **Reopen** reverses it |

After you add the document, run an eval over the dataset. The cases that
failed because the knowledge was missing should now pass.

## Drafting the missing content { #drafting-the-missing-content }

**Draft the missing content**, in an open topic, asks a model to write the
passage or FAQ entry the knowledge base is missing. It is one run of the
**Knowledge gap drafter**, a [system agent](concepts.md#system-agents) every
organization has. The drafter is shown the topic's 20 newest questions: what
each person asked, what the agent searched for and found, the answer the
person got, and any comment left with a thumbs-down.

The draft is kept on the topic, labelled as a draft, with a link to its run.
You can copy it or download it as Markdown. It is never added to the
knowledge base. The drafter does not know your
company's facts: where an answer needs a number, a date or a rule, it writes a
placeholder in square brackets for you to fill in. Drafting again replaces the
draft. Whoever may edit the drafter finds **Edit the drafter's instructions** on
the draft, and the drafter itself under **System agents** on the Agents page.

A draft names its sources: the documents of the knowledge base it builds on,
and the topic's questions it answers. Each one is verified before the draft is
kept - a document must belong to the topic's knowledge base, a question must be
one of the topic's - and one that is not is left out, never shown, and
counted on the draft. At most 12 sources are kept. A source deleted later is
no longer shown.

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
nothing left, and the next grouping pass removes it, with its draft. A draft is
the one text a topic keeps: it is written by a model from the questions, so it
may repeat something a person wrote. Credentials it repeats are redacted before
it is stored. Drafting sends the questions, answers and comments to the
drafter's model provider. See
[Data protection](data-protection.md#where-personal-data-lives).

## What gaps do not detect yet { #limits }

Gaps come from retrieval only. An answer in which the agent said it did not
know, or an answer rated down with a comment about missing information, is
not detected on its own. Detecting those needs a model and is tracked in
[#2135](https://github.com/vstorm-co/agenticos/issues/2135). When a rated-down
answer belongs to a run whose search was a miss, its comment is shown with the
question.
