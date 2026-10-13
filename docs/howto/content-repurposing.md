---
title: "Turn one article into social posts in your brand voice"
description: "Attach a short synthetic article and have an agent write one post per channel, each traceable to the source and within its channel's limits."
---

# Turn one article into social posts in your brand voice

Give an agent one article and a skill holding your voice rules and per-channel
limits, and have it write one post for LinkedIn, one for X and one newsletter
blurb. The fixture is short enough to check every claim in the posts against
the article by hand. This is a procedure to run, with one recorded run as a
reference. It does not measure how well the voice matches yours.

## What you need

- A [running installation](../install.md) with a model profile.
- No sandbox, embedding model or MCP connection — this agent only needs the
  [skills capability](../reference/capabilities.md#skills) and a chat
  attachment.

## Prepare the input

Save this as a skill, in **Skills → New skill**. Name it `brand-voice`, give
it a description such as "Tone, banned phrases and per-channel limits for
turning an article into social posts", and paste this body:

```text
Plain, confident, specific. Say what happened and what it means for the
reader. Use second person when addressing the reader, and "we" when
describing what the company did. State only facts, numbers and outcomes that
appear in the source article — never round a figure or add an outcome the
article does not give.

## Banned phrases

Never use any of: "game-changer", "revolutionize", "cutting-edge", "seamless",
"unlock your potential", "at the end of the day", "in today's fast-paced
world".

## Channel limits

| Channel | Limit | Shape |
|---|---|---|
| LinkedIn | 80-150 words | Open with the concrete result, two or three short paragraphs, at most one hashtag |
| X | 280 characters or fewer, counting spaces | One idea, no thread, no hashtag needed |
| Newsletter blurb | 40-60 words | One sentence hook, one sentence of detail, end with the placeholder [link] |

Write one post per channel from the attached article. Every claim in a post
must trace to a sentence in the article. If the article does not state a
number or outcome, the post does not state one either.
```

Then save this synthetic article, about 400 words, as `article.md`. The
figures are invented for this test; a fictional company, a fictional pilot,
nothing in it is real.

```text
Northwind Robotics cuts warehouse pick times in six-week pilot

Northwind Robotics, a fictional logistics-robotics company, ran a six-week pilot
of its updated picking robot, the Pallox-3, across three regional warehouses.
The pilot measured the time from an order arriving to an item leaving the pick
station.

Average pick time fell from 12 seconds to 9 seconds per item, a 25 percent
reduction, measured across 40,000 picks during the pilot. The Pallox-3's
battery lasts 8 hours per charge, up from 5 hours on the previous model,
which let two of the three sites run a full shift without a midday swap.

No worker injuries were recorded at any of the three pilot sites during the
six weeks, according to the internal safety log Northwind shared with pilot
staff. The robot's new obstacle sensor, added after last year's design
review, stops the unit within 4 centimeters of an unexpected object, compared
with 15 centimeters on the previous sensor.

Warehouse staff at the pilot sites were surveyed at the end of the six weeks.
68 percent said the robot's new charging dock was easier to use than the old
one; 12 percent reported no opinion; the remainder did not respond to that
question.

Based on the pilot results, Northwind plans to roll the Pallox-3 update out
to 40 additional warehouses during the fourth quarter. The rollout will
happen in four batches of ten sites, starting with the two regions that ran
the pilot. Each batch is expected to take one week to install and configure,
based on the installation time recorded during the pilot.

The Pallox-3 hardware itself did not change during the pilot; the
improvement came from a software update to the picking algorithm, which
Northwind's engineering team had been testing internally for four months
before the pilot began. The update is delivered over the air to existing
Pallox-3 units, so warehouses do not need to replace hardware to get the
faster pick times.

Northwind has not yet published pricing for warehouses outside the original
three pilot sites, and a company spokesperson said in the pilot debrief that
a decision on pricing for the Q4 rollout is still under review. The company
also declined to say whether the update would be offered to older Pallox-2
units.

This is a synthetic case study; Northwind Robotics, the Pallox-3 and every
figure above are invented for this test.
```

Reference facts to check against later: 25% faster (12s to 9s), 40,000 picks,
an 8-hour battery, a 4 cm sensor stop distance, 68% of staff finding the new charging
dock easier to use, a software-only update, no injuries, and a Q4 rollout to 40 sites in four
batches. The article also says what is *not* known yet: pricing for the rollout
and whether older Pallox-2 units get the update.

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, enable **Skills** and bind the `brand-voice` skill you just
   created.
3. Set the instructions below, then **Publish**.

```text
You repurpose one article into social posts.
Follow the bound brand-voice skill for tone, banned phrases and channel limits.
Write exactly one post per channel: LinkedIn, X and the newsletter blurb.
Every claim must trace to a sentence in the attached article. Do not invent a
fact, a number or an outcome the article does not state.
Label each post with its channel name.
```

## Run it

Open a new chat with the agent, attach `article.md` and send:

```text
Turn the attached article into one post per channel: LinkedIn, X and the
newsletter blurb.
```

## Check the result

| Check | Reference |
| --- | --- |
| X post length | 280 characters or fewer, including spaces |
| LinkedIn post length | 80-150 words |
| Newsletter blurb length | 40-60 words |
| Banned phrases | None of the seven phrases from the skill appear in any post |
| Every number and outcome | Traces to a sentence in `article.md` — 25%, 12s to 9s, 40,000 picks, 4 cm, no injuries, Q4 rollout to 40 sites |
| Same request with no file attached | The agent asks for the article rather than inventing one |

Count the X post's characters by hand or with a short script; do not trust the
model's own claim about length.

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. The agent called
    `load_capability` for `brand-voice`, then answered directly with all three
    posts. The X post ran 185 characters. The LinkedIn post ran 113 words and
    the newsletter blurb 50 words, both inside their limits. No banned phrase
    appeared in any post. Every number in all three posts — 25%, 12s to 9s,
    40,000 picks, the 4 cm sensor stop distance and the Q4 rollout to 40 sites
    in four batches — matched the article. Cost: 0.016 USD.

    With no file attached, the agent still loaded the skill, then said "I
    don't see any article attached to your message" and asked for it, instead
    of writing posts from nothing.

## When it goes wrong

- **A post exceeds its limit.** The skill states the limit as a rule, not a
  suggestion; tighten the instructions to say the agent must count before
  answering, or shorten the skill's own example lengths.
- **A banned phrase slips through.** Check the exact skill body is bound and
  was not shadowed by an older version — Skills keeps one version per skill,
  and a stale conversation may have loaded an earlier answer before an edit.
- **The agent invents a statistic.** Ask it to quote the sentence a number
  came from; a number it cannot quote back is one it invented.
- **The agent writes posts with no article attached.** If it does not refuse,
  tighten the instructions to require refusing when no file is present.

## Record the trial

Keep the article, the skill body, the three posts, the agent version and the
run in Activity. Keep a run where a limit was exceeded, too — it shows whether
the failure was the skill's wording or the model's arithmetic.

A person still decides whether the voice actually sounds like the brand and
whether a post is fit to publish. The character count and the banned-phrase
check are mechanical; the voice judgment is not.

## Next steps

Add a second brand's voice as a separate skill and bind whichever one a
conversation needs, rather than growing one skill with a variant per client.
See [Skills](../skills.md) for how a skill is scoped and shared.
