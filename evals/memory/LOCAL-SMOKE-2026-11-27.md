# Local memory smoke test — 2026-11-27

Baseline `0a2ed05e46`. The run used a fresh pgvector PostgreSQL database, a local
Redis instance, and the production `python -m app.worker --pools agent,workflow`
process. The published AgenticOS starter used OpenRouter Claude Sonnet 5.5.
Memory maintenance used OpenRouter GPT-6 Luna at low effort.

| Scenario | Observed result |
| --- | --- |
| Sonnet in fresh private conversations | `remember`, `correct_memory` and `recall` each passed. The prior preference remained in history after correction. `write_memory` persisted a private Ice Light working note. Atlas headcount was 20 as of July 2020, unknown as of July 2023 and 40 as of July 2026. Each date reached the recall tool. The one-off instruction caused no memory write. |
| Luna on the real queue | A Sonnet conversation queued `extract-memory` on completion. The worker finished the job and saved one claim with the exact user quote about the recurring Zinc Harbor heading. The assistant-only guess supplied in the fixture was absent from saved claims. A second delivery of the same payload kept the same claim ID. After erasure, a further delivery of the old payload completed with an empty ledger and no new Luna run. |
| Atlas/XYZ through Workflows | Sonnet recorded the private deadline and the owner reviewed its publication. A synthetic authenticated Gmail event ran the published workflow and added evidence to the same claim. Repeating its delivery produced a single workflow run. A signed synthetic CRM event ran a second published workflow and produced a dispute. A viewer could read shared evidence and was refused conflict resolution. An owner in another tenant was refused the read. The authorized owner selected December 3, and recall still returned December 1 for the earlier date. |

The Gmail test supplied a trusted synthetic delivery at the portal boundary. The CRM
test built and signed its request body. Each delivery went through admission, durable
dispatch and execution of the production `memory.observe` node. The worker checks
used persisted jobs, claim IDs and evidence. The ordinary extraction task allows one
automatic attempt. The repeat check deliberately delivered the same old payload again.

The targeted PostgreSQL replay passed all 26 tests. It exposed a SQLAlchemy
deprecation in the historical-revision query. The query now uses the same PostgreSQL
`distinct_on` extension as the other repositories. Note and recall receipts also show
that Sonnet sometimes tried a deferred tool before discovery. It recovered through
`search_tools` within the same turn. Keep those extra round trips visible in latency
measurements.

The model calls booked approximately **$0.5243** in the local run ledger, including
both Luna executions. The workflow nodes used the typed source data without a model
call. Raw receipts and worker logs were kept in the local ignored results directory.

## LongMemEval-S cost estimate

The estimate uses the existing five-arm harness. BM25 and both AgenticOS ledger
versions use deterministic input. Mem0 and Hindsight are the two arms with paid
ingestion in this estimate. Every arm uses the same Sonnet answer model. Prices are
in USD and exclude machine time, setup and human review.

| Campaign | 25 questions per arm | 500 questions per arm |
| --- | ---: | ---: |
| One deterministic retrieval arm with answers and grading | ~$0.15–0.31 | ~$2.8–6.1 |
| Three deterministic arms with answers and grading | ~$0.42–0.92 | ~$8.4–18.3 |
| All five arms, with extraction priced at Luna rates for Mem0 and Hindsight | ~$2–4 | ~$35–75 |

- **Answering.** Allow 2,000–4,000 billed input tokens and 150–400 billed output tokens
  per answer with the 12,000-character evidence cap. Sonnet costs $2/$10 per million.
  The official judge is budgeted separately at 700–1,300 input tokens and 10 output
  tokens with GPT-4o mini rates of $0.15/$0.60 per million, subject to the judge
  snapshot still being available. [Sonnet pricing](https://openrouter.ai/anthropic/claude-sonnet-5.5) ·
  [GPT-4o mini pricing](https://developers.openai.com/api/docs/models/gpt-4o-mini) ·
  [Official judge](https://github.com/xiaowu0162/LongMemEval/blob/main/src/evaluation/evaluate_qa.py)
- **Ingestion.** The authors describe roughly 115,000 history tokens across about 40
  sessions per question. For 500 questions, budget 57.5M base history tokens per
  extractor, multiplied by 1.3–2.5 for repeated context and prompts, plus 4M–10M
  generated tokens. Luna rates of $0.10/$0.50 per million yield about $9.5–19.4 per
  extractor. Budget up to $1.5 per extractor for small paid embeddings. The exact
  tokenizer, retain configuration, cache, retries and local embedding choice affect
  the bill. [LongMemEval data format](https://github.com/xiaowu0162/LongMemEval#-dataset-format) ·
  [Luna pricing](https://openrouter.ai/openai/gpt-6-luna) ·
  [Embedding pricing](https://openrouter.ai/openai/text-embedding-3-small)

Reserve **$10** for a 25-question calibration and **$100** for the 500-question
comparison if the cheap extractors are configured and measured usage supports the
forecast. Sonnet-priced retention would cost roughly **$190–390 per extractor**
at this volume. An additional AgenticOS extraction arm using Luna would add about
**$10–21** under the same assumptions. LongMemEval was left unrun.
