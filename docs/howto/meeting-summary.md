---
title: "Summarise a meeting transcript into decisions and action items"
description: "Paste a short synthetic transcript and check that the agent separates decisions from action items, names an owner and date for each, and flags the one task nobody claimed."
---

# Summarise a meeting transcript into decisions and action items

Build an agent that turns a pasted transcript into three short lists:
decisions, action items with an owner and a due date, and open questions.
The fixture transcript has one task that comes up but that nobody actually
agrees to own — the check that matters most is whether the agent reports
that honestly instead of assigning it to whoever is mentioned nearby. This
is a procedure to run, with one recorded run as a reference.

## What you need

- A [running installation](../install.md) with a model profile.
- No capability. This agent reads what is in the message and nothing else.

## Prepare the input

A short, synthetic transcript, invented for this page:

```text
Onboarding revamp sync — 12 March, 10:00–10:35
Jenna: Let's get through this quickly. Marcus, where are we with the signup
API changes?
Marcus: Mostly done. I can have the new field validation live by March 20.
Jenna: Good. Priya, the tooltip designs?
Priya: Almost there. I can deliver the final set by March 18, in time for
Marcus to wire them up.
Jenna: Great. Let's also decide on the survey step. Tomas, you said support
tickets show people dropping off there.
Tomas: Right, about a third of drop-offs happen on the survey screen. My
recommendation is to remove it entirely rather than shorten it.
Jenna: Agreed, let's remove the survey step from onboarding. Marcus, can you
fold that into the same API change?
Marcus: Yes, same PR.
Jenna: Decision made — the survey step is gone. Now, should the new tooltip
flow go to everyone at once, or beta first?
Priya: Beta first. We haven't tested it on mobile yet.
Marcus: Agreed, mobile rendering is still rough.
Jenna: Okay, decision: new tooltip flow ships to beta users first, general
release after that's clean.
Tomas: One more thing — the help center article on "how onboarding works"
is now out of date once the survey step is gone. Somebody should update it
before we ship.
Jenna: Good catch. Let's make sure that happens.
Priya: I can't take that on, I'm full up with the tooltip work through the
20th.
Marcus: Not mine either, that's not engineering's article.
Jenna: Okay, let's flag it and figure out who owns docs later this week.
Tomas: Compiling the onboarding-related support tickets into a report —
I'll do that, but I don't have a firm date yet, depends on how much backlog
I need to dig through.
Jenna: That's fine, just get it to us when it's ready.
Jenna: Last open question — do we sunset the old onboarding flow entirely,
or keep it behind a flag as a fallback for a few weeks?
Marcus: I'd lean toward keeping the flag, in case the new flow breaks
something we didn't catch in beta.
Priya: I don't have a strong opinion either way.
Jenna: Let's leave that open and revisit once beta feedback comes in.
Jenna: Okay, I think that's everything. Thanks all.
```

The reference: two decisions (drop the survey step; ship the tooltip flow to
beta first), four action items with an owner, one action item — updating the
help-center article — that both Priya and Marcus explicitly decline, and one
open question left for later.

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. Leave the Toolbox empty. Nothing here needs a tool.
3. Set a budget and a step limit for the trial.
4. Set the instructions below, then **Publish**.

```text
You turn a pasted meeting transcript into three sections: Decisions,
Action items, and Open questions.

For each action item, name the owner and the due date exactly as stated. If
a task is mentioned but nobody agreed to own it, list it under Action items
as unassigned and say so - never guess an owner, and never assign it to
someone who explicitly declined it in the transcript.

List a topic under Open questions only if the transcript does not record a
decision on it. Do not invent a decision, an owner, or a date the transcript
does not state.
```

## Run it

Paste the transcript straight into a new conversation, after a short
instruction:

```text
Summarise this meeting transcript into decisions, action items and open questions.

[paste the transcript]
```

Attaching it as a text file works the same way: an agent with no workspace
gets an upload's text pasted into the prompt, the same as a paste. See
[file processing](../file-processing.md#chat-file-uploads).

## Check the result

| Check | Reference |
| --- | --- |
| Decisions | Remove the survey step; ship the tooltip flow to beta first |
| Marcus's action item(s) | Field validation and the survey-step removal, due 20 March |
| Priya's action item | Final tooltip designs, due 18 March |
| Tomas's action item | Compiling the support-ticket report, with no date invented for it |
| The help-center article | Listed as unassigned, not given to Priya or Marcus |
| Open questions | Only the sunset-vs-fallback question, not a decision restated as a question |

Check the unassigned item first. An agent that quietly hands it to whichever
name appears closest in the transcript has failed the one check this page
exists for, even if every other line is right.

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. No tool calls — the whole
    answer came from one model request, for 0.0063 USD. It listed both
    decisions, gave Marcus two line items (field validation and the
    survey-step removal, both 20 March), Priya's tooltip designs at 18
    March, and Tomas's report with "no firm date — to be delivered when
    ready." The help-center article was listed as **"Unassigned (Priya and
    Marcus both declined; owner to be determined later this week)"** rather
    than assigned to either of them. The one open question was the
    sunset-versus-fallback decision, marked deferred.

## When it goes wrong

- **The unclaimed task gets assigned anyway.** This is the failure to watch
  for. Tighten the instructions further — naming the exact phrase "declined"
  or "unassigned" sometimes helps less than adding a second transcript where
  the same pattern repeats, to see if the first result was luck.
- **A due date appears that nobody said.** The model filled a gap because an
  action item without a date reads as incomplete. Check the instructions'
  last line is doing its job, and test with a transcript that has more than
  one dateless item.
- **An open question restates something already decided.** The model treated
  a decision made under pressure, late in the meeting, as still open. Point
  it at the exact line where the decision was made.
- **The three sections blur together.** With a longer, messier transcript,
  ask for the sections in a fixed order and check each one only has what
  belongs in it.

## Record the trial

Keep the transcript, the exact prompt, the agent version, the model, and the
reply. A person still checks the unassigned item against the transcript
directly — this is exactly the kind of small, easy-to-miss detail a fast
read of a long summary skips.

## Next steps

Turning each action item into an actual tracked task, with the owner
notified, is a separate step covered in
[turn meeting notes into tasks](meeting-to-tasks.md). This page stops at the
summary a person reads and checks.
