# Council

Three delegates review the work, one strong model from each of three
different providers, at high reasoning effort, in parallel. Each delegate
scores the work out of 10 per round; a fresh review after fixes is a new
round, and the loop runs until every delegate scores at or above the
agreement threshold. The scores land on the run manifest and render as the
table the council skill puts in a PR description.

This is Theo's tstack council skill as a capability, not a new review
process invented here. The skill file at
`backend/app/core/catalog/skills/council-review/SKILL.md` is the procedure; this
capability is how an agent runs it.

## Why a capability, and why one tool

A review round is a decision the agent makes mid-run - "is this ready?" - so
it is a tool the model calls, not instructions baked in at build time. One
tool, `run_council_review`, because one call is one round: the agent fixes
what the delegates found and calls it again, and the round number on the
manifest is what makes "reviewed twice" a checkable fact rather than a
feeling.

## What it deliberately does not do

- **No substitution.** A member whose model did not resolve, or whose review
  fails, is reported `unavailable` with the reason. Swapping in another
  provider's model would break the one-model-per-provider shape the scores
  are comparable under, and a round that quietly became a two-delegate review
  would read as a three-delegate one.
- **No invented scores.** A delegate that gives no score records `no_score`.
  The table shows exactly that, and the round is not satisfied.
- **No scope creep.** The cap on rounds (`max_rounds`, default 3) is what
  stops repeated reviews from growing the work. The delegates judge the work
  as it stands; they do not propose work outside its scope.
- **No sol-loop.** The council does not fix what it finds, run checks, or
  iterate on its own. The agent fixes, then asks for a fresh round.
- **No eval cases.** Scores are per-round judgements of one piece of work,
  not a benchmark suite with cases to pass.
- **No migration.** Scores live in the run manifest's JSONB, beside the
  requests and the run reviewer's corrections. There is no table to migrate
  and no score to query across runs.

## Models

Each member reviews on its profile's **primary** model only. A profile's
fallback chain is never used here: a fallback would silently substitute
another provider when the first is down, and a council with two delegates on
one provider is not a council. The runner resolves the profiles and the
factory hands the resolved models to the builder; the capability never
touches the vault.

## Voice

A council review runs in the agent's text twin, not on a realtime call: a
review takes minutes a call cannot wait through, and its delegates are
ambient model calls. `voice="hand_off"`.
