# Published results and evaluation budgets

Checked 2026-11-18. No numbers below are AgenticOS measurements. Published
results describe a model **and its surrounding system**, not an inherent model
score. Different prompts, retrieval, judges, dataset revisions and reasoning
budgets prevent a fair ranking across unrelated reports.

## Separate benchmarks

- **AgentDojo:** simulated tool-use task utility, plus separate adversarial
  prompt-injection measurements when attacks are enabled. Our adapter currently
  runs only workspace utility tasks, not attacks.
- **LongMemEval:** answering from long conversation histories, including changed
  facts and preferences. S, M and oracle are different conditions.
- **AppWorld:** end-to-end task execution across simulated applications, graded
  against application state. It is neither of the above.

## Published results for the priced models

“Not found” means this source search did not establish a result for that exact
version. It is not zero and does not assert that no result exists anywhere.
No exact-version result below was established as a model vendor's own
AgentDojo/LongMemEval evaluation.

| Model | AgentDojo, exact version | LongMemEval, published external system |
| --- | --- | --- |
| Opus 5.5 | Not found | 94.8% (474/500), gbrain frozen-retrieval reader replay [1] |
| Sonnet 5.5 | Not found | 92.4% notes; 93.0% direct (500 each), same replay [1] |
| GPT-6.1 Sol | Not found | 92.8% (464/500), same replay [1] |
| GPT-6.1 Terra | Not found | Not found |
| GLM 5.3 / Prime | Not found | Not found as the answering model |
| Kimi K3.1 Pro / K2.5 | Not found | Not found for the specified S protocol |
| DeepSeek V4.1 Flash | Not found | Not found for this exact endpoint/version |
| DeepSeek V4 Pro 0813 | Not found | Not found for this exact dated version |

[1] [gbrain reader replay, 2026-10-07](https://github.com/garrytan/gbrain-evals/blob/main/docs/benchmarks/2026-10-07-longmemeval-w10b-reader-replay.md).
All questions were graded with the official rubric on `gpt-4o-2024-08-06`.
The retrieval system had been tuned on LongMemEval-S: the authors label these
**development**, not holdout results. Claude used low adaptive effort; Sol used
medium effort. The same report's reader-only batch costs are $24.01 for Opus,
$11.77/$11.30 for Sonnet and $7.12 for Sol; these are historical gbrain costs,
not our OpenRouter quotes or full memory ingestion costs.

Related DeepSeek evidence does exist: [EverMind's LongMemEval-S report](https://evermind.ai/blogs/multi-round-retrieval-letting-the-model-decide-when-to-stop-searching)
reports **92.48%** for `DeepSeek-v4-pro`, averaged across five extraction
backbones. That is an EverOS pipeline measurement, with an undated model name.
It cannot be assigned to `deepseek-v4-pro-0813`, V4.1 Flash, or a bare model.
Using GLM or Kimi as a judge or extraction model also does not establish their
answering-model accuracy.

[AgentDojo's own result page](https://agentdojo.spylab.ai/results/) explicitly
says it is not a leaderboard because attack/defense coverage differs. Its public
table includes older models, such as Claude 3.7 Sonnet (88.66% clean utility,
77.27% utility under `important_instructions`, 7.31% targeted attack success).
Those figures do not belong in the Sonnet 5.5 row.

## OpenRouter cost scenarios, USD

The [price snapshot](openrouter-prices.json) contains the exact model IDs,
retrieval timestamp and pricing fields from the public
[OpenRouter catalog](https://openrouter.ai/api/v1/models). Prices are the catalog
quotes, not a guaranteed provider route. They exclude caching, batch discounts,
tax/credit fees, judge models, embeddings, memory ingestion, external tools,
sandbox compute and retries.

These are arithmetic scenarios, **not observed benchmark usage**:

- **AgentDojo default two tasks:** assume each task uses 20,000 input and 2,000
  output tokens across all its turns: 40,000 input + 4,000 output total.
- **AgentDojo 97 clean task runs:** same assumption: 1.94M input + 0.194M output.
  This represents the original four-suite clean workload, not an implemented
  full-suite command in our workspace-only adapter. Attacks/repeats multiply it.
- **LongMemEval-S 500-question whole-context reference:** assume 115,000 input +
  1,000 output per question: 57.5M input + 0.5M output. The upstream S history
  length is roughly 115k with its reference tokenizer; actual tokenizers and
  memory retrieval change usage substantially. This is not the cost of an
  AgenticOS ingest/retrieve implementation.

All output allowances include reasoning. The cost formula is
`input_tokens * prompt_rate + output_tokens * completion_rate`.
A token ceiling is not a dollar cap; use provider spending controls.

| Exact OpenRouter ID | Input / output per 1M | AgentDojo 2 tasks | AgentDojo 97 clean runs | LongMemEval-S 500 reference |
| --- | ---: | ---: | ---: | ---: |
| `anthropic/claude-opus-5.5` | $4 / $20 | $0.2400 | $11.64 | $240.00 |
| `anthropic/claude-sonnet-5.5` | $2 / $10 | $0.1200 | $5.82 | $120.00 |
| `openai/gpt-6.1-terra` | $1 / $5 | $0.0600 | $2.91 | $60.00 |
| `openai/gpt-6.1-sol` | $2 / $10 | $0.1200 | $5.82 | $120.00 |
| `z-ai/glm-5.3` | $0.0699 / $1.4 | $0.0084 | $0.41 | $4.72 |
| `z-ai/glm-5.3-prime` | $1.68 / $5.28 | $0.0883 | $4.28 | $99.24 |
| `moonshotai/kimi-k3.1-pro` | $0.2403 / $8.4023 | $0.0432 | $2.10 | $18.02 |
| `moonshotai/kimi-k2.5` | $0.5 / $2.5 | $0.0300 | $1.46 | $30.00 |
| `deepseek/deepseek-v4.1-flash` | $0.0507 / $0.2028 | $0.0028 | $0.14 | $3.02 |
| `deepseek/deepseek-v4-pro-0813` | $0.111 / $4.44 | $0.0222 | $1.08 | $8.60 |

GPT-6.1 Terra Pro and Sol Pro have the same listed per-token rates as their
non-Pro counterparts, but may consume more output tokens. Reasoning settings
also affect token count, not just latency. The listed GPT long-input surcharge
starts at 272k prompt tokens, above this scenario's 115k per request.
No fixed percentage saving from caching is assumed.

## Benchmarks featured in model launches

The sources below establish use by the named vendor, not independent replication.
Keep version, harness, effort, safeguards and any fallback model alongside scores.

| Official release/card | Relevant benchmarks shown | Relevance to AgenticOS |
| --- | --- | --- |
| [Anthropic Opus 5.5](https://www.anthropic.com/claude-opus-5-5) | Terminal-Bench 4.0, FrontierCode, CursorBench, GDPval-AA v2.1, AutomationBench, OSWorld 2.1 | Coding, artifacts, business workflows and optional desktop work |
| [OpenAI GPT-6.1 Terra](https://openai.com/index/introducing-gpt-6-1-terra/) | Agents' Last Exam, OSWorld 2.1, Terminal-Bench 4.0, MMMU-Pro | Computer use and terminal tasks; visual reasoning is a component test |
| [Z.ai GLM 5.3](https://huggingface.co/zai-org/GLM-5.3) | Toolathlon Verified, Terminal Bench 2.1/3.0, DeepSWE, SWE-Marathon, GDPval-AA v2 | Tool execution and long coding work |
| [Moonshot Kimi K3](https://huggingface.co/moonshotai/Kimi-K3) | Toolathlon-Verified, BrowseComp, Terminal-Bench 2.1, DeepSWE, SWE-Marathon, GDPval-AA v2 | Do not transfer K3 scores to K3.1 Pro or K2.5 |
| [DeepSeek V4 Pro](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro) | Toolathlon, BrowseComp, Terminal Bench 2.0, SWE Verified/Pro/Multilingual, GDPval-AA | Tool execution, research, coding and deliverables |

Useful vendor-reported examples: Opus 5.5 scores 66.4% on Terminal-Bench 4.0
at xhigh effort; GPT-6.1 Terra scores 50.3% on that version at max effort.
GLM 5.3 reports 73.0 on Toolathlon Verified. DeepSeek V4 Pro Max reports 51.8
on Toolathlon and 83.4 on BrowseComp. Toolathlon and Toolathlon Verified, like
Terminal-Bench 2.0 and 4.0, must not be combined into a single score column.

For AgenticOS, prioritize **Toolathlon** after the existing clean AgentDojo
checks, **LongMemEval-S** for actual isolated memory, **BrowseComp** for research,
and **Terminal-Bench** for the coding tools. AppWorld is an alternative
multi-application environment; avoid integrating two heavy application worlds
at once before measuring the benefit. Keep adversarial AgentDojo separate from
clean task success. Add τ²-bench if conversational policy-driven workflows become
a focus. GUI benchmarks and professionally judged GDPval work are later tracks.

Primary benchmark sources:
[Toolathlon](https://github.com/hkust-nlp/Toolathlon),
[BrowseComp](https://openai.com/index/browsecomp/),
[Terminal-Bench](https://www.tbench.ai/),
[τ²-bench](https://github.com/sierra-research/tau2-bench).
