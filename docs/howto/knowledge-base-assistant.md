---
title: "Answer questions across a document library with citations"
description: "Put four small synthetic policy documents in one collection and check that the agent finds the right one, combines two of them, and admits what neither covers."
---

# Answer questions across a document library with citations

Build an agent that answers from a small HR policy library instead of one file.
The fixture has four short documents in one collection: one question is answered
by a single document, one needs two of them combined, and one is not covered at
all. Checking a multi-document answer means reading both source passages, not
just the reply. This is a procedure to run, with one recorded run as a reference.

For a single document with no collection to manage, start with
[your first document agent](first-document-agent.md) instead. This page is the
step after that: several documents, and an answer that has to cite the right one.

## What you need

- A [running installation](../install.md) with a model profile.
- An embedding provider and a vault key for it — the recorded run used
  OpenRouter's `text-embedding-3-small`. [Set up a knowledge base](set-up-knowledge-base.md)
  covers the create dialog in full.
- No sandbox and no other capability.

## Prepare the input

Four short Markdown files, saved as separate uploads. The fixture is invented,
and two policies deliberately share a number so that one question needs both.

`expense-policy.md`:

```text
Employees may claim reimbursement for client meals up to 40 EUR per person.
Travel booked more than 14 days in advance must use economy class for flights
under 6 hours. Mileage for a personal car used on company business is
reimbursed at 0.35 EUR per kilometre. Receipts are required for any claim over
15 EUR. Claims must be submitted within 30 days of the expense.
```

`remote-work-policy.md`:

```text
Employees may work remotely up to 3 days per week without prior approval.
A fully remote arrangement needs sign-off from the department head and HR.
Remote employees must be reachable during core hours, 10:00 to 16:00 in their
local time zone. Equipment for a home office is reimbursed once per employee,
up to 400 EUR, on the same 15 EUR receipt threshold as the expense policy.
```

`onboarding-checklist.md`:

```text
A new employee's manager requests a laptop and accounts in the first week.
IT provisions access within 2 business days of the request. The employee
completes the compliance training module within 30 days of their start date.
The 400 EUR home-office equipment allowance from the remote work policy is
requested through the same IT ticket as the laptop.
```

`travel-booking-guide.md`:

```text
Book flights and hotels through the corporate travel portal. Economy class is
the default for flights under 6 hours, matching the expense policy's advance-
booking rule. Hotel stays are capped at 180 EUR per night in tier-1 cities and
120 EUR elsewhere. A trip that combines client meetings and a conference needs
the sponsoring manager's approval before booking.
```

The reference facts: a client meal is capped at 40 EUR (expense policy alone).
The home-office allowance is 400 EUR, and it is requested through the laptop's
IT ticket — one number from the remote-work policy, one step from the
onboarding checklist. Nothing here states a resignation notice period.

## Build the agent

1. In **Knowledge → New**, name the collection, expand **Embeddings**, and
   choose the provider and model that serve your key — the recorded run used
   OpenRouter and `text-embedding-3-small`. This choice is frozen once the
   collection exists.
2. Create the collection, then upload the four files. Wait for each to reach
   `done` before moving on.
3. Create an agent in **Agents → New agent** and select your model profile.
4. In **Toolbox**, enable **Knowledge search** and bind the collection you just
   filled. Leave `default_top_k` at its default; four short documents do not
   need more.
5. Set the instructions below, then **Publish**.

```text
Answer questions from the bound HR policy collection.
Cite the document you used for each fact.
If the answer draws on more than one document, name each one.
If the collection does not cover the question, say so rather than guessing.
```

!!! info "Two settings worth knowing before you scale this up"

    `self_query_enabled` (off by default) has the model infer filters such as a
    source, a document type or a date range from a question like "policies
    updated last quarter" — useful once documents carry that metadata, and not
    needed for four files with none. `parent_context` (off by default) hands
    back the text around a matched chunk instead of the chunk alone, which
    helps when an answer sits at the edge of one. Both are read, never written,
    from the model's own explicit filters, and neither widens which collections
    or tenant an agent can reach. See [the capability reference](../reference/capabilities.md#knowledge-search).

## Run it

Ask each question in a fresh conversation, so an earlier answer cannot leak
into the next one.

```text
How much can I claim for a client meal?
```

```text
I am fully remote. How much is the home-office equipment allowance, and how do I request it?
```

```text
What is the notice period if I want to resign?
```

## Check the result

| Check | Reference |
| --- | --- |
| Client meal answer | 40 EUR, cited to `expense-policy.md` |
| Home-office answer | 400 EUR, cited to `remote-work-policy.md`, with the request step cited to `onboarding-checklist.md` |
| Resignation question | States the collection does not cover it, and does not invent a figure |
| Retrieved passages in Activity | The client-meal run's top match is `expense-policy.md`; the home-office run's matches include both source documents |
| A question about last week's travel bookings | Answered from `travel-booking-guide.md`, not blended with the other three |

Read the retrieved passages in Activity, not only the reply. A citation naming
the right file with the wrong number, or the right number from the wrong file,
both look correct in the chat.

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter, `default_top_k` at 5. The
    client-meal question called `search_documents` once and answered "up to
    €40 per person," citing `expense-policy.md`, for 0.0133 USD. The
    home-office question retrieved three documents and answered "up to €400,"
    citing `remote-work-policy.md` for the figure and `onboarding-checklist.md`
    for "the same IT ticket used to request your laptop," for 0.0181 USD. The
    resignation question retrieved the three least-relevant documents, found
    nothing in them and answered "does not appear to contain a document
    covering resignation notice periods," for 0.0135 USD.

    The first attempt at this agent bound no collection to the spec — a mistake
    in test setup rather than the product — and the model answered from its own
    training instead of admitting it had nothing bound. `search_documents` was
    never called. Binding the collection and republishing fixed it; the
    difference between "no tool call happened" and "the tool ran and found
    nothing" is the first thing to check when an answer looks confident but the
    source is missing.

## When it goes wrong

- **The agent answers fluently with no citation.** Check Activity for whether
  `search_documents` was called at all. A knowledge capability bound to no
  collection contributes nothing, silently, rather than a tool that always
  fails.
- **A document is missing from an answer that should use it.** Check the
  document's status in the collection. A `processing` or failed document is
  invisible to search however clearly a person can read it.
- **The resignation question gets a confident but wrong answer.** The
  instructions' last line — "say so rather than guessing" — is what turns
  silence into a refusal. Test it deliberately, the way the third question
  here does.
- **Two documents that should combine only ever answer from one.** Raise
  `default_top_k`, or check whether the phrasing of the question favours one
  document's vocabulary over the other's.
- **A synced folder should feed this collection instead of manual uploads.**
  See [configure sync sources](configure-sync-sources.md) — the same
  collection can mix uploads and a scheduled sync.

## Record the trial

Keep the four files, the questions, the agent version, the model and embedding
profiles, and the retrieved passages from Activity for each run — not just the
replies. A person still judges whether a citation actually supports what the
agent said, and whether "not covered" was the right call rather than a lazy
one.

## Next steps

Once retrieval holds up across documents, put the agent in front of people:
[Slack](slack-handbook-assistant.md) is the same pattern with a channel in
front of it. For a corpus too large to upload by hand,
[configure sync sources](configure-sync-sources.md) instead.
