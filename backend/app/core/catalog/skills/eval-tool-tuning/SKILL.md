---
name: eval-tool-tuning
description: Use when the user asks to tune a tool against eval cases, or why a tool keeps failing them.
category: engineering
---

# Eval tool tuning

Score one tool against eval cases that are already judged, and draft tuning
proposals from the failures. A tuning run is the layer on top of the
failure-learning loop (#32): the loop's eval tries judge cases, this
workflow asks how one tool behaved across them and what should change
about it.

## What a tuning run needs

- One tool, by name.
- A set of judged eval cases: each case with what its answer was supposed
  to say, whether the judge said it passed, what the answer said, and
  every tool call the case's run made. Get these from an eval try (#32's
  try runner) - never judge an answer yourself, and never invent a
  verdict for a case nobody ran.

## 1. Score the tool

Call `record_eval_tool_tuning` with the tool and the judged cases. One
call is one tuning run: it scores the tool, classifies each failure, drafts
one proposal per failure class, and records the run on the manifest. At
most 3 tuning runs per run.

The seven failure classes, and what each one means:

- `not_called` - no tool ran on the case. The tool was never reached.
- `wrong_tool` - another tool was picked instead.
- `transient` - the tool failed because of a timeout, connection, or rate-limit error.
- `authorization` - the tool rejected the request with 401 or 403.
- `bad_arguments` - the tool failed with an argument or validation error.
- `unknown` - the tool failed for another reason, or the error type was not recognized.
- `wrong_answer` - the tool ran cleanly, but the answer still missed what
  the expectation asked for.

## 2. Present the drafts, do not apply them

The call returns the score and the draft proposals - one per failure
class - with their kind, title, and the failing cases as evidence. Show
them to the person and let them decide:

- `tool_choice` - route the requests to this tool, or prefer it over the
  tool that was picked instead.
- `tool_parameters` - constrain the tool's arguments so the model stops
  calling it with arguments that fail.
- `prompt_wording` - tell the tool's caller what the answer must say.

A proposal is a draft until a human applies it: an instruction change
goes through the failure-learning loop's proposal apply (eval-gated,
audited); a skill change through the learned-skill path. **Never apply a
proposal yourself, never edit instructions or a skill to "fix" a tuning
run, and never present a draft as a fix that has been made.** A proposal
that has been applied is tried again against the same cases - old fails
and new passes is what proves it, not the draft.
