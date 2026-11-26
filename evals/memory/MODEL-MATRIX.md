# Models for the memory evals

Research snapshot from 2026-11-26. Use separate model comparisons for the interactive
agent and the background reader. Keep the answering model fixed when comparing
AgenticOS with other retrieval systems on LongMemEval.

## Shortlist

OpenRouter standard endpoint prices in USD per million tokens, in/out. The
dated snapshot is the resolved model identity from the catalog.

| Role | OpenRouter model ID | Snapshot | Input / output | First pass |
| --- | --- | --- | ---: | --- |
| Agent | `anthropic/claude-sonnet-5.5` | 2026-09-28 | $2.00 / $10.00 | Premium reference, start at medium effort. Also our historical reference for background extraction. |
| Agent | `openai/gpt-6.2-sol` | 2026-11-17 | $2.00 / $10.00 | Premium challenger, start at medium effort. Compare cost per pass and latency even at identical listed rates. |
| Agent | `deepseek/deepseek-v4-flash-0731` | 2026-07-31 | $0.06 / $0.18 on DeepInfra FP8 | Existing budget baseline. Keep the same revision for continuity and record the actual route. |
| Maintenance | `anthropic/claude-haiku-5.5` | 2026-10-07 | $0.10 / $0.50 | First low-effort candidate for grounded extraction. |
| Maintenance | `openai/gpt-6-luna` | 2026-09-22 | $0.10 / $0.50 | Second low-effort candidate. Same list price as Haiku, compare errors and real usage. |
| Optional agent | `google/gemini-4-neon` | 2026-11-18 | $3.00 / $15.00 | Third premium candidate if the first two leave important gaps. |

[Sonnet](https://openrouter.ai/anthropic/claude-sonnet-5.5),
[Sol](https://openrouter.ai/openai/gpt-6.2-sol),
[DeepSeek](https://openrouter.ai/deepseek/deepseek-v4-flash-0731),
[Haiku](https://openrouter.ai/anthropic/claude-haiku-5.5),
[Luna](https://openrouter.ai/openai/gpt-6-luna),
[Gemini](https://openrouter.ai/google/gemini-4-neon).
The [catalog API](https://openrouter.ai/api/v1/models) advertises tools and
structured outputs for the shortlist. Record the routed provider, model version,
reasoning effort, caching and price when available. Use a standard endpoint.
Sol's fast tier charges $4/$20 and OpenRouter lists other DeepSeek providers at
different prices. Prefer one provider route per model if the eval profile can
pin it. Mark runs with incomplete cost in the scorecard.

## Run the paired comparison

Prepare the disposable [personal eval stack](../personal/README.md#run-agenticos-in-docker)
and set `AGENTICOS_PERSONAL_EVAL=1`. Create distinct OpenRouter Sonnet and Sol
profiles at medium effort on that same published starter, with one dedicated
key in the test vault. Disable Memory maintenance in the test organization for
the live tool probe. Set `OPENROUTER_API_KEY` for the independent extraction
replay. From `backend/`:

```sh
uv run python ../evals/memory/compare_models.py \
  --organization-id "$ORG_ID" --user-id "$USER_ID" \
  --sonnet-profile "$SONNET_PROFILE" --sol-profile "$SOL_PROFILE" \
  --out ../evals/memory/results/model-comparison
```

Each interactive model gets the same eight isolated tool cases and the three-turn
persisted memory probe. Each background model gets all 53 extraction cases. The
new output directory contains a `summary.json` with deterministic passes,
quality and technical failures, missing cases, spend completeness, total wall time,
and p50/p95 case latency by model and phase. Raw case receipts and logs sit beside it.
The live probe stops at the first failed step and the summary counts remaining
steps as missing. An incomplete or failed comparison exits nonzero.

The AgenticOS cap defaults to $5 per model across both phases. The background
runner stops between cases at $0.25 per model. Override these with
`--agent-max-usd` and `--maintenance-max-usd`.

## What the public evidence measures

| Source | Observed result | Relevance |
| --- | --- | --- |
| [OpenRouter tool-calling collection](https://openrouter.ai/collections/tool-calling-models) | DeepSeek V4.1 Flash 1017, Hy4 flash and DeepSeek V4.1 Flash led token volume at the snapshot. | Trailing seven-day adoption signal across models that support tools. Useful for finding candidates. |
| [Zapier AutomationBench 1.0.6](https://zapier.com/benchmarks) | Strict task success over 657 simulated SaaS tasks per effort. [Sonnet 5.5](https://zapier.com/benchmarks/claude-sonnet5_5-report) reached 23.3% at medium ($0.29/task) and 44.7% at max ($1.08). [Sol 6.2](https://zapier.com/benchmarks/gpt6_2-sol-report) reached 40.2% at medium ($0.18) and 41.2% at high ($0.21). Gemini 4 Neon reached 56.32% at xhigh. | The closest public signal for choosing tools and producing correct business state. Effort and harness settings matter. Compare the effort settings we actually use. |
| [AutomationBench-AA](https://artificialanalysis.ai/evaluations/automationbench-aa) and [BFCL V4](https://gorilla.cs.berkeley.edu/leaderboard.html) | AA scores partially completed objectives and zeros tasks with a guardrail violation. BFCL isolates function selection, argument structure, relevance and multi-turn calls. For example, its published Sonnet 4.5 FC result is 73.24 overall. | Keep tool and business-state metrics separate. The example BFCL entry is an older snapshot. |
| [JSONSchemaBench](https://arxiv.org/abs/2501.10868), [ExtractBench](https://arxiv.org/abs/2602.12247) | JSONSchemaBench tests constraint coverage and output quality. ExtractBench checks individual extracted fields against source documents, with major degradation as the schema grows. | Grade schema acceptance and factual grounding separately. Bounded conversation transcripts need their own paired extraction scores. |
| [Anthropic Haiku 5.5 model report](https://www.anthropic.com/claude-haiku-5-5) | Anthropic reports Haiku 5.5 ahead of Luna on GDPval-AA v2.1 (1620 vs 1437 Elo) and AA-Briefcase v1.1 (1578 vs 1336 Elo). | The vendor's professional-work results support testing Haiku first. Our paired extraction replay supplies the evidence for the final model choice. |

## What to measure in AgenticOS

- **Agent tools.** Run the same authored cases and agent version for every candidate.
  Record correct tool, typed arguments, forbidden write/share attempts and final
  answer. Score stateful `remember` → `correct_memory` → `recall` separately
  with maintenance disabled and verify the ledger after each new conversation.
- **Memory maintenance.** Replay the same 53 cases at low effort on Haiku and Luna.
  Count exact quotations from user messages, extra or duplicate claims, missed
  facts, corrections that change the subject, false saves on negative cases,
  schema retries, p95 and cost per passing case. Sonnet is a quality reference on
  the same slice. Report `briefing` separately if testing that job as well.
  The `memory.observe` workflow node records already-typed Gmail or CRM
  observations without a model call. Count any model step added to a workflow
  under that workflow's cost.
- **Company invariants.** Keep company replay as a model-free check of permissions,
  provenance and stored history. Inspect cross-scope disclosure and forbidden
  publication as individual failures even when the overall pass rate is high.
- **Model selection.** Freeze case IDs, code SHA, agent version, profile, effort and
  the reasoning/output caps. Run a small accounting pass, then repeat the
  paired slice in both languages. Review disagreements before enlarging the
  sample. Use a fixed answer model and judge for memory-system comparisons.

The [personal eval runbook](../personal/README.md) has the case selection and
live-probe commands. The prior [AgenticOS baseline](../personal/results/2026-11-20-agenticos-baseline.md)
used DeepSeek and passed 45/50 on the whole historical slice under deterministic
scoring. The [historical background baseline](../personal/results/2026-11-22-background-context-baseline.md)
used Sonnet and passed 50/50 on the old extraction set for $0.260. Those
denominators belong to the original runs.

## Cost forecast from our telemetry

These are model-token estimates using historical AgenticOS runs and current
standard prices. Context, tool round trips, retries, reasoning, routing and
cache behavior change the current bill.

| Pilot workload | Assumed billed input / output | Forecast |
| --- | ---: | ---: |
| 25 agent cases on one premium model | 2.49M / 68k, half the Nov 20 agent baseline | ~$5.66 per model, ~$11.32 for both premium models |
| 25 agent cases on historical DeepSeek route | Half of the observed 50-case bill | ~$0.30 |
| 53 Memory maintenance cases on one small model | 103k / 4.4k, scaled from the Nov 22 extraction run | ~$0.013 per model |
| 53 Memory cases plus 53 Briefing cases on one small model | 325k / 14k from the two background suites | ~$0.040 per model |
| 53 Memory maintenance cases on Sonnet | Same extraction volume at $2/$10 | ~$0.25 |
| 100,000 maintenance calls on one small model | 1,951 input / 83 output per call | ~$23.66 before retries, at the same telemetry mix |

Live probes, non-model tools and judge calls add to these estimates. The
LongMemEval campaign has a separate budget. Start the focused AgenticOS smoke
with a spend ceiling per profile and the background replay with an explicit
stop threshold. The background threshold is checked between cases, so the last
in-flight case can exceed it. Use a dedicated test key with its own cap for an
absolute provider spend limit.
