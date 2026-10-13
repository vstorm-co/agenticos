---
title: "Answer new-hire questions with context files and skills"
description: "Bind a short standing-facts context file and a procedure skill to one agent, and check which one answers which kind of question."
---

# Answer new-hire questions with context files and skills

Build a new-hire helpdesk that always knows a handful of small, stable facts and
only reaches for a written procedure when the question actually needs one. The
two capabilities behind that are [context files](../context.md) and
[skills](../skills.md), and this page exists because picking the wrong one is the
usual reason an agent either ignores what it was told or never opens what it
needed. This is a procedure to run, with one recorded run as a reference.

## Which one fits

| | Holds | The model sees it |
| --- | --- | --- |
| **Context file** | Standing facts, small and stable — payroll timing, the IT channel | Always (`inject`), or on demand (`link`) |
| **Skill** | A procedure for one kind of task — how to request access | Only when the model decides that task is what is happening |
| **Knowledge collection** | A corpus too large to read in full — a whole handbook, every policy PDF | Only the chunks a search returns |

The onboarding guide below is short and always relevant, so it is a context
file. "How do I get access to a system" is a procedure with steps and an
exception, so it is a skill. If your onboarding material is instead a fifty-page
handbook, bind it as a [knowledge collection](set-up-knowledge-base.md) and keep
this page's pattern only for the short, standing facts. See
[skills or knowledge?](../skills.md#skills-or-knowledge) for the same distinction
from the skill side.

## What you need

A [running installation](../install.md) with a model profile. No sandbox and no
embedding model — both files here are small enough to inject or load whole.

## Prepare the input

A context file of standing facts:

```markdown
# Acme Robotics — new-hire quick facts

- Payroll runs on the last business day of the month.
- The standard laptop is a MacBook Pro; loaner laptops are requested from IT, not HR.
- The internal help channel for IT questions is #it-help.
- Health insurance enrollment is open during your first 30 days; after that, only
  during the November open-enrollment window.
```

A skill for the one procedure new hires ask about most:

```markdown
# Requesting access

Most access requests go through the #it-help channel, not a person directly.

1. Post in #it-help naming the system and the reason you need it.
2. IT grants standard tools (chat, email, laptop) within one business day.
3. Anything touching customer data (the CRM, production databases) needs your
   manager's written approval first - tag them in the same thread.
4. Access to the payroll system is never granted through chat; email
   payroll@acme-example.com instead.
```

Acme Robotics is invented. The reference facts: payroll on the last business
day, a MacBook Pro by default, and CRM access needing a manager's approval
first.

## Build the agent

1. In **Context → New**, create a file named `onboarding-guide`, paste the
   facts above, set **Mode** to `inject`, and give it a description a person
   would recognise later.
2. In **Skills → New**, create `request-access` with the procedure above and a
   description written for the model: *"When somebody asks how to get access to
   a tool, a repository, a system, or is not sure who grants it."* — a linked
   skill is chosen from its name and this line alone.
3. Create an agent in **Agents → New agent** and select your model profile.
4. In **Toolbox**, enable **Context** and bind `onboarding-guide`. Enable
   **Skills** and bind `request-access`.
5. Set the instructions below, then **Publish**.

```text
You are Acme Robotics' new-hire helpdesk assistant.
Answer from the standing facts you were given, and use a bound skill's
procedure when a question is about how to do something.
If you are not sure, say so rather than guessing.
```

## Run it

Ask a standing fact first, then a procedure question:

```text
When does payroll run, and what laptop will I get?
```

```text
How do I get access to the CRM?
```

## Check the result

| Check | Reference |
| --- | --- |
| Payroll and laptop question | Answered directly, no tool call — the context file is already in the prompt |
| CRM access question | Calls `load_capability` for `request-access` before answering |
| The CRM answer | Names the manager's written approval as the first step, not just "post in #it-help" |
| A question the context file does not cover (e.g. "what's the dress code?") | Says it does not know, rather than inventing a policy |
| Editing the context file afterwards | The next run reflects the edit with nothing republished on the agent |

The first two rows are the check that matters: one answer comes from text
sitting in every prompt, the other from a tool call the model chose to make. If
either happens the other way around, the wrong capability was reached for.

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. The payroll/laptop question
    used 914 input tokens with **no tool call** and answered: *"Payroll runs on
    the last business day of the month... The standard laptop is a MacBook
    Pro"*. Cost 0.004 USD.

    The CRM question called `load_capability` with `{"id": "request-access"}`,
    got back the skill's full body, and answered: *"Since the CRM touches
    customer data, there's a specific process... Get your manager's written
    approval first... Post in #it-help. Tag your manager in the same
    thread"*. Cost 0.009 USD.

## When it goes wrong

- **A standing fact is missing from an answer.** Check the context file's
  **Mode**. A `link` file is not in the prompt at all until the model decides to
  read it — for facts that must never be missed, use `inject`.
- **The skill never loads.** The model chooses it by name and description alone;
  a description that reads like a title ("Access requests") tells it less than
  one written as *when to reach for this*.
- **The agent recites the skill for every question.** The skill's description is
  too broad, or the instructions do not distinguish "standing fact" from
  "procedure" clearly enough for the model to tell which this question is.
- **An edited context file does not change the answer.** Confirm you edited the
  organization's file and not a copy — context files are bound by id, and there
  is no per-agent fork of one.
- **A skill proposal appears instead of a direct answer.** The agent may try to
  *improve* the skill mid-conversation; that is a proposal for a person holding
  `skills:edit` to apply or discard, not something a run applies on its own. See
  [skills](../skills.md#an-agent-can-propose-a-change-a-person-makes-it).

## Record the trial

Keep both files' content and ids, the agent version, the two questions and
answers, and whether each one used a tool call. A person still writes and edits
the standing facts and the procedure — this pattern only decides where each
piece of text lives, not who is right about payroll dates.

## Next steps

The same agent can be bound to a Slack bot for a team channel instead of the
console — see [answer a handbook question in
Slack](slack-handbook-assistant.md), which walks through binding, linking
accounts and checking which run belongs to whom. If the onboarding material
grows past a page or two, move it into a [knowledge
collection](set-up-knowledge-base.md) instead of stretching an injected context
file.
