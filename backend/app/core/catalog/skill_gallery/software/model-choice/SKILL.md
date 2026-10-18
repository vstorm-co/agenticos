---
name: model-choice
description: Pick a model for an agent by quality, speed, cost and where data may go - and say why.
category: engineering
---

# Choosing a model

Look up current prices and models with web search before recommending one -
they change monthly. Cite the page.

## The four questions

1. **How hard is the job?** Reasoning over several documents, writing code or
   planning steps needs a frontier model. Classifying, extracting or short FAQ
   answers run well on a small, cheap one.
2. **How fast must it answer?** A chat widget wants a quick model; a nightly
   report does not care.
3. **How much will it run?** Price × messages per month. Estimate it out loud.
4. **Where may the data go?** Some companies need a model in their own region,
   their own cloud, or open weights they run themselves.

## Recommend

One model, the reason in a sentence, and the cheaper fallback: "Claude Sonnet for
the answers; Haiku would be a third of the cost if quality holds." Offer to
switch later - the model is one setting.

## Never

Recommend a model the organization has no key for without saying how to add one.
