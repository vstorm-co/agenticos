# Council { #council }

Three delegates review the work before it goes out: one strong model from
each of three different providers, at high reasoning effort, in parallel.
Each delegate scores the work out of 10, and a fresh review after fixes is a
new round. The loop runs until every delegate is satisfied.

This is the council skill as a capability. The procedure lives in the
`council-review` skill (`backend/app/core/catalog/skills/council-review/SKILL.md`),
which says when to ask for a review; this page says what the capability does
with the answer.

## How a round works

The agent calls `run_council_review` with the work and the context it needs.
One call is one round: the call fans the work out to the delegates, each on
its own provider's model, and returns their scores with their findings.

After a round, the agent fixes what the delegates found and calls it again
for a fresh round, until every delegate scores at or above the agreement
threshold. The cap on rounds is what stops repeated reviews from growing the
work: fix what was asked, nothing more.

A delegate's review is read-only. It judges the work as it stands; it does
not edit it and does not propose work outside its scope.

## Configuration

| Field | Default | What it is |
|---|---|---|
| `members` | — | Exactly three delegates, each with a name, a distinct provider, and a model profile |
| `agreement_threshold` | `8` | The score out of 10 every delegate must reach for a round to satisfy the council |
| `max_rounds` | `3` | How many review rounds one run may ask for (1–5) |

Each member reviews on its profile's **primary** model only. A profile's
fallback chain is never used here: a fallback would silently substitute
another provider when the first is down, and a council with two delegates on
one provider is not a council.

## The table

Every round is recorded on the run manifest, and renders as the table the
council skill puts in a PR description:

```markdown
## Council review

Rounds: 2

| Delegate | Round 1 | Round 2 |
| --- | --- | --- |
| Claude Opus | 7/10 | 9/10 |
| GPT Sol | 8/10 | 10/10 |
| Gemini Pro | 7/10 | 9/10 |
```

A delegate that gives no score reads `no score`. One that could not be
reached reads `unavailable`, with the reason. Neither is ever given a score
it did not give, and an unavailable member is never substituted.

## What it does not do

- **Fix what it finds.** The council judges; the agent fixes, then asks for
  a fresh round.
- **Keep scores anywhere but the manifest.** Scores live in the run
  manifest's JSONB, beside the requests. There is no table to migrate and no
  score to query across runs.
- **Run on a live call.** A review takes minutes a call cannot wait through,
  so the capability runs in the agent's text twin, handed off from the call.

The capability needs the `agents:delegate` scope, because its delegates are
model calls the agent hands work to.
