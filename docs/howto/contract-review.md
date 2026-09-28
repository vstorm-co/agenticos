---
title: "Review a contract against your checklist"
description: "Bind a first-pass review skill to an agent, attach a short synthetic services agreement, and check it finds both planted issues and the missing clause without giving legal advice."
---

# Review a contract against your checklist

Build an agent that reads an attached contract and produces a structured
extract and a list of deviations from a checklist — not an opinion on
whether to sign. The fixture is a short synthetic services agreement with
two planted problems and one clause missing outright. This is a procedure to
run, with one recorded run as a reference.

## What you need

- A [running installation](../install.md) with a model profile.
- The **skills** capability, bound to a review-checklist skill. This page
  installs the gallery's `legal/document-review-first-pass` — see
  [skills](../skills.md#getting-skills-into-an-organization) for writing your
  own instead. The gallery also carries `legal/contract-clause-library`, for
  looking up an approved clause and its fallback position once you have one
  to check against; this fixture does not need it. A ready-made
  `legal/contract-reviewer` agent template combines both.
- No sandbox. An attached text file is read from the prompt directly; see
  [file processing](../file-processing.md#chat-file-uploads).

## Prepare the input

A short services agreement, invented for this page, saved as
`services-agreement.txt` and attached in chat:

```text
MASTER SERVICES AGREEMENT

This Agreement is made between Acme Consulting Ltd ("Provider") and Nimbus
Retail Ltd ("Client"), effective 1 January 2027.

1. Term
The initial term is 12 months from the effective date.

2. Services
Provider will deliver monthly analytics reporting as described in Schedule A.

3. Fees and Payment
Client will pay Provider 5,000 EUR per month, payable within 30 days of
invoice.

4. Confidentiality
Each party will keep the other's confidential information confidential
during the term and for 3 years after termination.

5. Liability
Each party's liability under this Agreement is unlimited.

6. Termination
Either party may terminate this Agreement for uncured material breach on 30
days' written notice.

7. Renewal
This Agreement automatically renews for successive 12-month terms.

8. Assignment
Neither party may assign this Agreement without the other party's prior
written consent.
```

Two planted issues: clause 5 caps nothing (uncapped liability), and clause 7
renews automatically with no notice window to stop it. One clause is missing
outright: nothing in the agreement names a governing law or a jurisdiction.

## Build the agent

1. In **Skills → Skill gallery**, install `Document review first pass` from
   the legal shelf.
2. Create an agent in **Agents → New agent** and select your model profile.
3. In **Toolbox**, enable **Skills** and bind the skill you just installed.
4. Set the instructions below, then **Publish**.

```text
You produce a structured extract and a list of deviations from the bound
review checklist skill. You do not advise, do not conclude a clause is
acceptable, and do not redraft. Everything you produce is checked by the
person who reviews it before it is relied on.

Use the Document review first pass skill for what to extract and how to flag
deviations. Cite the clause number for every extracted term and every
deviation. Flag anything the checklist expects that the agreement does not
contain.
```

## Run it

Attach `services-agreement.txt` to a new conversation and send:

```text
Review this services agreement against the checklist.
```

## Check the result

| Check | Reference |
| --- | --- |
| Liability | Flagged as deviating — no cap, cl. 5 |
| Renewal | Flagged as deviating — no opt-out notice window, cl. 7 |
| Governing law and jurisdiction | Flagged as missing entirely, not invented |
| Every extracted term and deviation | Cites a clause number |
| Tone | States facts and deviations; does not conclude the agreement is safe, risky, or fine to sign |
| A question asking whether to sign | Declines to advise, and points back to the fee earner who reviews the output |

Read the deviations against the source clauses yourself. A deviation that
cites the wrong clause number, or a missing-clause list that invents an
item the agreement actually has, both read as thorough in the chat.

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. The extract named cl. 5's
    liability as "unlimited" with "no exclusion of indirect/consequential
    loss," cl. 7's renewal as having "no opt-out/break notice mechanism,"
    and listed "Governing law & jurisdiction" as absent under both the
    deviations and a separate missing-items table, alongside indemnities and
    change of control — items the checklist expects that this short fixture
    never included. It closed by stating the extract "requires verification
    by the fee earner responsible for this matter before being relied upon."
    Cost: 0.0249 USD.

    The first attempt failed before producing anything: the model called
    `load_capability` with the guessed id `document-review-first-pass`
    (hyphenated, matching the gallery's own naming), which does not exist —
    a bound skill's id is its exact stored name, "Document review first
    pass" — retried with a second wrong guess, and the run ended with
    "the agent could not finish this turn," for 0.0083 USD spent on the two
    guesses. A fresh attempt in a new conversation used the right id on the
    first call. Retrying once is the practical fix; if it keeps guessing
    wrong, naming the skill in the instructions with its exact stored name
    removes the guess entirely.

## When it goes wrong

- **The run fails with "could not finish this turn" before any output.**
  See the recorded run above — a model call to `load_capability` guessed the
  skill's id instead of copying it from the catalog. Retry in a fresh
  conversation, or state the skill's exact name in the instructions.
- **The agent tells you whether to sign.** Tighten "you do not advise" and
  test it directly with a follow-up question — a checklist tool that answers
  "yes, this is fine" the moment somebody asks is answering past its brief.
- **A deviation has no clause number.** The instructions ask for one on
  every item; a missing citation on an otherwise correct finding is still
  worth flagging, since the next reader cannot check it without one.
- **The missing-clause list invents something the agreement has.** Read the
  source directly. The checklist expects roughly a dozen standard items; a
  short fixture will always be missing several, and the model has to get the
  ones that are genuinely absent right, not just produce a long list.
- **Two agents bound to the same skill give different checklists.** The
  skill is one row, shared by name; check nobody has an unpublished proposal
  pending on it under **Skills**. See
  [an agent can propose a change; a person makes it](../skills.md#an-agent-can-propose-a-change-a-person-makes-it).

## Record the trial

Keep the exact agreement text, the reply, the agent version, the skill's own
version, and the model. A person still checks every citation against the
source and decides what to do about each deviation — the agent's brief is to
surface them, not to close them.

## Next steps

Add `legal/contract-clause-library` once you have an approved position to
check clauses against, so a deviation can be reported with the actual
fallback rather than only "this differs from standard." For a longer
agreement with several documents to cross-check, [knowledge search](knowledge-base-assistant.md)
answers a different question than this page: retrieving a passage from a
large corpus, rather than reviewing one attached document end to end.
