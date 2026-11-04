# text.compare

Scores how alike two texts are, from 1 (the same) to 0 (nothing in common),
without a model and at no cost. Use it to measure how much a person edited a
draft, to compare a draft with a reference, or to notice that a document changed.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | `TextCompareInput` | `a`, `b` (each at most 100,000 characters) |
| `out` | output | `TextCompareOutput` | `score`, `changed_ratio`, `method`, `unit`, `a_units`, `b_units` |

## Methods

`char_ratio` counts characters an editor would not touch, `token_f1` the words
the texts share (order ignored), `line_diff` the lines left unchanged. By default
spacing within a line, line edges and blank lines are ignored (line breaks still
count; only `token_f1` ignores them); case, punctuation and quoted mail are
ignored only when set.

## What it will not do

It does not judge meaning: two texts that say the same in other words score low.
A missing config or input is `TEXT_COMPARE_NOT_CONFIGURED`; a text over the limit
ends the run with `INVALID_BINDING` before the step runs.
