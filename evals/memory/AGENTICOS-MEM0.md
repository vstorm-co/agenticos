# AgenticOS and Mem0 OSS on LongMemEval-S

## Paired comparison

Both systems ingest the same chronological sessions and answer the same questions.
The frozen manifest pins the dataset digest, question IDs, cutoff, retrieval limit and
evidence budget. Sessions after the cutoff are excluded before either system sees them.
The comparison uses top 8 and 12,000 evidence characters, as in the existing harness.
These settings define the local protocol. Mem0's published top-50 run used a different
evidence budget and the managed v3 memory pipeline. Its published OSS GPT-5 run also
used a different embedder. [Managed results](https://github.com/mem0ai/memory-benchmarks/blob/main/results/platform/longmemeval_top50_results.json)
· [OSS results](https://github.com/mem0ai/memory-benchmarks#oss-with-different-extraction-models)

| Stage | AgenticOS | Mem0 OSS |
| --- | --- | --- |
| Ingest | Production maintenance handler stores claims and source evidence in PostgreSQL | OSS `/memories` extracts and stores memories in its native index |
| Extraction model | OpenRouter `openai/gpt-6-luna`, low effort, profile without fallbacks | OpenRouter `openai/gpt-6-luna`, low effort, without fallback models |
| Retrieve | Production ledger recall across the person's profile and personal agent claims | OSS `/search` scoped to the matching synthetic user |
| Answer | One shared prompt, `anthropic/claude-sonnet-5.5`, low effort, 600 completion tokens | Same |
| Judge | Official LongMemEval rubric and `gpt-4o-mini-2024-07-18` via the official script | Same |

Use single-turn answers with the same evidence envelope and no tools in this controlled
comparison. Each system keeps its own extraction prompt, storage, indexing and ranking.
The AgenticOS replay creates one completed private chat run per historical session and invokes
the production worker handler synchronously. This measures its extraction and persistence
without queue wait. The claims are written at replay time, so the retrieval step reads
current claims from a database containing only pre-question input. It gets source dates from
the seeded conversations. Real historical `as_of` and retrospective `known_at` stay covered by
the deterministic ledger and enterprise replay. Differences in the way production maintenance
and Mem0 prioritize user and assistant evidence are part of the comparison. Mem0 OSS receives
the date in source metadata. The AgenticOS maintenance prompt consumes the production turn
timestamps directly. No consolidation schedule runs during this replay.

Use a paired 25-question calibration, then all 500 questions. Record paired accuracy and
its interval, category accuracy, abstention, source hit/recall, empty results, p50/p95
latency and spend by stage. Reconcile Mem0 extraction and embeddings with its dedicated
provider key or metered gateway. Its REST search response does not contain usage.
The grader sees only the question, gold answer and hypothesis. Keep technical failures
visible, and audit paired disagreements before interpreting the gap.

## Full product LongMemEval

Use both paths in each isolated case. Replay the earlier sessions in order. For each
session, Sonnet receives the original dated transcript as data in a separate review
call. Its production memory tools can save a useful note or handle an explicit
remember/correct request in the source. Luna processes the original dated session
through the maintenance handler and writes supported claims. The agent's synthetic
review call is excluded from maintenance. The frozen history is independent of the
held-out question and the gold answer.

At question time, the same agent identity starts a fresh chat. The run can see the
memory overview and use `recall`, `list_memory` and `read_memory` to answer. The eval
guard blocks side-effecting tools on this turn and the runner skips maintenance on it.
Some sessions need no durable note. The harness measures actual note and claim rows,
tool calls, per-stage spend and answer latency rather than forcing a write or a read
on every case.

| Variant | History | Question | What it measures |
| --- | --- | --- | --- |
| Full product | Sonnet saves useful Notes or acts on explicit memory requests; Luna maintains Memories | Live Sonnet with memory tools in a fresh chat | End-to-end user experience with the two write paths |
| Controlled comparison | Luna inside both memory systems | Shared direct recall and Sonnet answer prompt | Memory quality with the answer prompt and model held fixed |
| Authored personal evals | Scripted explicit save, correction, handoff and mixed-source scenarios | Fresh chat checks expected writes and then recalls them | Correct tool selection, expected persistence and ACLs |

The full product run uses the standard agent runner with a frozen memory-only eval spec
on the starter identity. It reports answer quality and does not score document recall
from tool narration. Grade its hypotheses using the same judge and slice as the
controlled comparison. A comparison against the existing Mem0 arm is a system result
under different workflows. The controlled pair remains the comparison under shared
answer conditions.

If adding maintainer-generated Notes later, use a separate experiment with source-linked
drafts and compare against this run. Track wrong or stale handoffs, duplicate content,
evidence coverage and when a person actually needs to review a draft.

## Commands

Use a separate migrated local `memory_bench*` AgenticOS database and a disposable
Mem0 instance. Pin the checkout revisions and configuration in each label. On AgenticOS,
bootstrap the published starter with personal memory enabled and configure its organization
with a positive Memory maintenance budget. Use the same database in `POSTGRES_*` and
`MEMORY_BENCH_AGENTICOS_DSN`. The CLI creates one new member per question and keeps the
rows and spend receipts until the disposable database is dropped.

For Mem0 OSS, the current server config format is verified against revision
[`a330119`](https://github.com/mem0ai/mem0/blob/a330119bda245ad05bf1d5e6779fc588b5f19443/server/main.py).
In the loopback instance's configuration use the following LLM section, set
`OPENROUTER_API_KEY` in the server environment, and leave its endpoint at OpenRouter.
Use `text-embedding-3-small` for the Mem0 embedder and configure that provider separately.
The stock shell/API config can be updated by an admin through `POST /configure`; retain the
rest of the disposable instance's actual config. [LLM adapter](https://github.com/mem0ai/mem0/blob/a330119bda245ad05bf1d5e6779fc588b5f19443/mem0/llms/openai.py)
· [Mem0 settings](https://github.com/mem0ai/mem0/blob/a330119bda245ad05bf1d5e6779fc588b5f19443/docs/components/llms/config.mdx)

```json
{
  "llm": {
    "provider": "openai",
    "config": {
      "model": "openai/gpt-6-luna",
      "reasoning_effort": "low"
    }
  }
}
```

From AgenticOS `backend/`, with local service credentials and paths set in the shell:

```sh
B=../evals/memory
DATA="$B/data/longmemeval_s_cleaned.json"
OUT="$B/results/mem0-luna-pilot"
EXTRACT_MODEL=openai/gpt-6-luna
ANSWER_MODEL=anthropic/claude-sonnet-5.5
export MEMORY_BENCH_ANSWER_URL=https://openrouter.ai/api/v1/chat/completions

uv run python "$B/run.py" prepare --dataset "$DATA" --out "$OUT/slice.json" \
  --limit 25 --seed 17 --top-k 8 --evidence-chars 12000

uv run python "$B/run.py" retrieve --dataset "$DATA" --manifest "$OUT/slice.json" \
  --arm agenticos-maintenance --maintenance-agent "$AGENTICOS_STARTER_ID" \
  --extract-model "$EXTRACT_MODEL" --allow-service-calls \
  --label "$AGENTICOS_REVISION_AND_CONFIG" --out "$OUT/agenticos.jsonl"

uv run python "$B/run.py" retrieve --dataset "$DATA" --manifest "$OUT/slice.json" \
  --arm mem0 --url "$MEM0_URL" --extract-model "$EXTRACT_MODEL" --allow-service-calls \
  --label "$MEM0_REVISION_AND_CONFIG" --out "$OUT/mem0.jsonl"

for arm in agenticos mem0; do
  uv run python "$B/answer.py" --retrieval "$OUT/$arm.jsonl" \
    --out "$OUT/$arm.answers.jsonl" --usage "$OUT/$arm.usage.jsonl" \
    --model "$ANSWER_MODEL" --openrouter-effort low --max-output-tokens 600 \
    --input-per-million 2 --output-per-million 10 --max-usd "$ANSWER_ARM_CAP"
done
```

Add `--estimate-only` to the answer command to get the reservation without a model call.
Before grading, confirm both usage logs show the same provider-returned answer model.
In the official LongMemEval checkout pinned at
[`9e0b455`](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/src/evaluation/evaluate_qa.py),
grade both hypotheses with `python src/evaluation/evaluate_qa.py gpt-4o-mini "$ABS_HYPOTHESES" "$ABS_DATA"`.
Supply the two graded JSONL files in the same order to `run.py compare`:

```sh
uv run python "$B/run.py" compare "$OUT/agenticos.jsonl" "$OUT/mem0.jsonl" \
  --grade "$AGENTICOS_GRADES" --grade "$MEM0_GRADES" > "$OUT/comparison.json"
```

Use a distinct output directory and `--limit 500` for the full run. Check model availability
before the paid run. OpenAI has announced retirement of both legacy snapshots. The
GPT-5 variant below is an estimate. Running it later with GPT-5 as judge requires the
Mem0 evaluator or an explicit GPT-5 judge adaptation because the official pinned
LongMemEval script has no GPT-5 entry. [OpenAI retirement schedule](https://developers.openai.com/api/docs/deprecations)

## Run the full product variant

After preparing the same slice, use the published starter and the OpenRouter Sonnet
model profile ID. The starter must be runnable by a member. The agent budget covers
Sonnet's transcript reviews and question turns. Luna uses the Memory Maintenance
budget set on the disposable organization. Begin with 25 questions. Measure actual
agent review spend in `usage.jsonl` before budgeting the full set. Those reviews
process the source sessions and sit outside the controlled comparison estimate below.

```sh
uv run python "$B/product.py" --dataset "$DATA" --manifest "$OUT/slice.json" \
  --out "$OUT/product" --agent "$AGENTICOS_STARTER_ID" \
  --agent-profile "$SONNET_PROFILE_ID" --agent-budget "$PRODUCT_AGENT_CAP" \
  --allow-service-calls --label "$AGENTICOS_REVISION_AND_CONFIG"
```

Grade `product/answers.jsonl` with the same pinned official judge. Pass
`product/report.jsonl` and its grades to `run.py compare` alongside the other arms.
Keep `product/usage.jsonl` for tool counts, persistence counts and stage costs. A
partially completed run has visible rows for finished cases and is refused by compare.

## Estimated API cost

Both sides, standard rates, no cache discount. Machine time, analyst time and agent
tool-loop calls are separate.

| Configuration | 25 questions per system | 500 questions per system |
| --- | ---: | ---: |
| Luna extraction, Sonnet answer, GPT-4o mini judge | ~$1.2–2.7 | ~$25–53 |
| Luna extraction, GPT-5 answer and judge | ~$1.2–2.8 | ~$25–55 |
| GPT-5 extraction, answer and judge on both systems | ~$14–29 | ~$273–576 |
| GPT-5 on all three stages for Mem0 OSS alone | ~$7–14.5 | ~$136–289 |

Per system at 500 questions, estimate 57.5M source tokens from the dataset's roughly
115K per question. With input replay and prompts at 1.3–2.5×, extraction bills
74.75M–143.75M input and, by assumption, 4M–10M generated tokens including reasoning.
Answers use 2K–4K input and 150–400 generated tokens per question. For GPT-5 judging
allow 700–1,300 input and 100–400 generated tokens per question. For the official
GPT-4o mini judge allow the same input and 10 generated tokens. Add up to $1.50 total
for Mem0 embeddings. Recalibrate against actual usage on the frozen pilot, especially
GPT-5 reasoning and each system's prompt volume.

Rates per million input/output tokens are $0.10/$0.50 for Luna, $2/$10 for Sonnet,
$1.25/$10 for GPT-5 and $0.15/$0.60 for GPT-4o mini. The GPT-5 configuration mirrors
the public OSS model roles. Its dollar figure estimates our two-arm protocol and is
not Mem0's reported bill. [Corpus size](https://github.com/xiaowu0162/LongMemEval#-dataset-format)
· [Luna](https://openrouter.ai/openai/gpt-6-luna)
· [Sonnet](https://openrouter.ai/anthropic/claude-sonnet-5.5)
· [GPT-5](https://developers.openai.com/api/docs/models/gpt-5)
· [GPT-4o mini](https://developers.openai.com/api/docs/models/gpt-4o-mini)
· [Embeddings](https://openrouter.ai/openai/text-embedding-3-small)
