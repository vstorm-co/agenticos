# Memory benchmarks

Use the [existing personal-assistant datasets](../personal/README.md) for regression tests,
LongMemEval for paired retrieval and answer comparisons, and synthetic PostgreSQL claims
for ledger performance. The three tracks measure different parts of the system.

## Implementation against the plan

| Planned work | Evidence in this PR | Open work |
| --- | --- | --- |
| Ledger correctness and timeline | The existing ledger preserves effective dates on publication, ranks before applying the limit, and supports `as_of` and `known_at`. The PostgreSQL replay covers headcount, retroactive correction, relevance after noise and history pagination. | Measure quality and latency on the frozen slices. |
| Personal and organization memory | Settings → Memory offers personal and organization views, Memories and Notes, business objects, history, publication review and conflicts. A business project can exist independently of an AgenticOS workspace. Existing rows remain readable. | General alias suggestions, auditable object merge/split and bulk identity backfill. |
| Agent tools and maintenance | `remember` handles explicit memory, `write_memory` keeps agents' notes, and maintenance extracts admissible claims from conversations. External observations use `memory.observe` inside Workflows. | A single end-to-end quality benchmark that exercises real agent tools, model extraction, persistence and recall across a large corpus. The retrieval harness below seeds deterministic transcript chunks. |
| Gmail and CRM | Existing Gmail and signed webhook triggers admit observations to a common contract. The CRM fixture exercises that contract. There are PostgreSQL tests for chat/Gmail agreement, conflicts, retry, preview and revocation. | A direct native CRM-to-memory path, real provider runs and end-to-end lease-loss testing. Use the signed relay for the implemented CRM path. A dedicated memory-specific connector manager was removed in favor of Workflows. |
| Proactivity and Inbox | Workflows can route the action's typed result, including `changed`, through existing workflow steps. Replay checks the observation and its change signal. | Versioned decision policy, transactional and idempotent Inbox delivery, recipient authorization at delivery, correction cards and shadow results. The existing replay does not assert delivery to Inbox. |
| Quality, scale and governance | The three TSV datasets, context packets and enterprise replay cover initial cases. This directory adds frozen comparison slices, paired metrics and a synthetic scale runner. | Published measurements, a frozen enterprise holdout with PL/EN pairs, concurrent tenant load, index rebuild and erasure after restore. An ontology or graph backend and decision models remain separate experiments. |

See the [implementation plan](https://agenticos-memory-research.vstorm-3469.chatgpt.site/implementation.html),
the [enterprise integration tests](../../backend/tests/integration/test_memory_enterprise.py),
and the [workflow node contract](../../backend/app/workflows/nodes/memory_observe/README.md).

## 1. Reuse the product regressions

Run the following from `backend/`. The first command validates the authored corpus. The next
two run the production background prompts with a supplied model and budget. The context
replay compares the same evidence packets with the same model. The enterprise replay uses
synthetic data in a disposable PostgreSQL database and checks persisted outcomes and ACLs.

```sh
uv run python ../evals/personal/run.py
uv run python ../evals/personal/run.py --suite memory --model "$MODEL" --max-usd "$CAP"
uv run python ../evals/personal/run.py --suite briefing --model "$MODEL" --max-usd "$CAP"
uv run python ../evals/personal/context_run.py --model "$MODEL" --max-usd "$CAP" \
  --report ../evals/memory/results/context.jsonl
uv run python ../evals/personal/memory_replay.py --list
uv run python ../evals/personal/memory_replay.py
```

The `agenticos` TSV also runs in the personal eval stack. Use that stack's documented
`--suite agenticos` and `--live-memory` commands for tool calls and cross-session memory.
The authored TSVs and context packets are regression data. Freeze new company cases by
scenario and tenant before tuning prompts or ranking. The CRM fixture is synthetic.

## 2. Freeze a LongMemEval slice

Download `longmemeval_s_cleaned.json` from the [official dataset](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned).
Save datasets and run outputs under the ignored `data/` and `results/` directories.

```sh
# From backend/
B=../evals/memory
DATA="$B/data/longmemeval_s_cleaned.json"
OUT="$B/results/pilot"
uv run python "$B/run.py" prepare --dataset "$DATA" --out "$OUT/slice.json" \
  --limit 25 --seed 17 --top-k 8 --evidence-chars 12000
```

Preparation validates dates, samples across question categories including abstention and
prints the number of sessions and transcript bytes. It performs zero model calls.
Each question has an independent history. Inputs are sorted by session timestamp and
sessions after the question cutoff are excluded. Systems receive opaque session IDs.
Gold answers, gold session labels, and per-turn `has_answer` fields stay out of the adapters
and the answer prompt. Publish the selected case IDs alongside results. The pilot is
balanced by category and its pooled score differs from the distribution of the full set.

## 3. Run the retrieval arms

```sh
uv run python "$B/run.py" retrieve --dataset "$DATA" --manifest "$OUT/slice.json" \
  --arm bm25 --label raw-session-bm25 --out "$OUT/bm25.jsonl"

# Set MEMORY_BENCH_AGENTICOS_DSN to an already migrated, disposable local database.
# The URL uses postgresql+asyncpg:// and a database name beginning with memory_bench.
uv run python "$B/run.py" retrieve --dataset "$DATA" --manifest "$OUT/slice.json" \
  --arm agenticos-ledger --label memory-mvp --out "$OUT/ledger.jsonl"

# Use a separate migrated database at the baseline SHA and an existing baseline checkout.
# The merge base used in the plan is bb09fedf19b10f897c6a55dbdcd76a212dc9a275.
MEMORY_BENCH_AGENTICOS_DSN="$LEGACY_DSN" \
  uv run python "$B/run.py" retrieve --dataset "$DATA" --manifest "$OUT/slice.json" \
    --arm agenticos-legacy --legacy-checkout "$LEGACY_CHECKOUT" \
    --label pre-mvp --out "$OUT/legacy.jsonl"

# Set the URLs to local self-hosted instances. Pin their builds, model and index settings.
uv run python "$B/run.py" retrieve --dataset "$DATA" --manifest "$OUT/slice.json" \
  --arm mem0 --url "$MEM0_URL" --allow-service-calls \
  --label "$MEM0_REVISION_AND_CONFIG" --out "$OUT/mem0.jsonl"
uv run python "$B/run.py" retrieve --dataset "$DATA" --manifest "$OUT/slice.json" \
  --arm hindsight --url "$HINDSIGHT_URL" --allow-service-calls \
  --label "$HINDSIGHT_REVISION_AND_CONFIG" --out "$OUT/hindsight.jsonl"

uv run python "$B/run.py" compare "$OUT/legacy.jsonl" "$OUT/ledger.jsonl" \
  "$OUT/bm25.jsonl" "$OUT/mem0.jsonl" "$OUT/hindsight.jsonl" > "$OUT/retrieval-summary.json"
```

For the PostgreSQL arms, point each backend's normal migration configuration at the
corresponding disposable pgvector database and migrate that checkout's schema. The
DSN used by retrieval only accepts a loopback host. The fixture creates a new tenant
and user per question and rolls the transaction back. Set both databases to comparable
PostgreSQL versions and configurations. Both arms seed the same 600-character chunks
and call their checkout's actual recall implementation. The MVP supplies the question date
as `as_of`. The old reader uses its original current lookup over the already filtered
history. These two arms isolate ledger retrieval from memory extraction.

Mem0 and Hindsight retain the same history through their own extraction. Set
`MEMORY_BENCH_MEM0_API_KEY` and `MEMORY_BENCH_HINDSIGHT_API_KEY` if your local
services require authentication. Each run uses fresh user IDs or banks. Use disposable
stores, since these results remain in the services for inspection. The instances can call
paid providers during retention and recall. Configure caps there before opting in. Mem0
returns its declared session metadata when available. Hindsight uses synchronous retain,
the question timestamp and recalled world/experience facts. See the
[Mem0 OSS REST server](https://github.com/mem0ai/mem0/blob/main/server/main.py),
[Hindsight Retain](https://hindsight.vectorize.io/developer/api/retain) and
[Hindsight Recall](https://hindsight.vectorize.io/developer/api/recall).

All arms share the same maximum number of ranked evidence units and total evidence
characters. A unit may be a session, a transcript chunk or an extracted fact. The final
unit may be truncated. Consequently, hitting a gold session measures provenance and
still needs answer grading to show that its relevant text survived. Unattributed evidence
can help the answerer, but cannot earn provenance credit. Results include hit,
unique-session recall, all-gold coverage, MRR, empty rate, provenance coverage, ingest
latency and recall latency by category. BM25 recall time includes its ephemeral index
construction. JSONL preserves case order and failures. Comparison rejects incomplete
runs and mismatched budgets and reports paired bootstrap intervals against the first arm.
Treat paired intervals as exploratory on the pilot and inspect the reported pair count.
Empty retrieval on an abstention case is distinct from correct answer abstention.

## 4. Generate and grade answers

Use one pinned Chat Completions model for all arms. Set
`MEMORY_BENCH_ANSWER_URL` to its full `/chat/completions` endpoint and
`MEMORY_BENCH_ANSWER_API_KEY` if needed. Supply the actual per-million input and output
rates for that model, a fixed output limit and a per-arm budget. The provider must
support `temperature: 0`, `max_completion_tokens` and reported token usage.

```sh
uv run python "$B/answer.py" --retrieval "$OUT/ledger.jsonl" \
  --out "$OUT/ledger.answers.jsonl" --usage "$OUT/ledger.usage.jsonl" \
  --model "$MODEL" --input-per-million "$INPUT_RATE" --output-per-million "$OUTPUT_RATE" \
  --max-usd "$ARM_CAP" --estimate-only
```

Repeat without `--estimate-only` when ready, using the same model and settings for
each arm. The report records provider-model IDs, latency, token counts and calculated
costs. The official [LongMemEval judge](https://github.com/xiaowu0162/LongMemEval)
accepts the hypothesis JSONL directly. Pin the judge revision and use the same judge
on every arm.

```sh
# In a separately prepared official LongMemEval checkout.
python src/evaluation/evaluate_qa.py "$JUDGE" "$ABS_HYPOTHESES" "$ABS_REFERENCE_DATASET"

# From AgenticOS backend/. --grade order matches the retrieval reports.
uv run python "$B/run.py" compare "$OUT/legacy.jsonl" "$OUT/ledger.jsonl" \
  --grade "$LEGACY_GRADES" --grade "$LEDGER_GRADES" > "$OUT/answer-summary.json"
```

### Budget worksheet

The earlier plan reserved **USD 350** in direct costs and **3.5–7 engineer-days** for
the initial quality campaign. Treat this as a spending envelope. Start with the same
25 questions per arm and calibrate on observed costs before increasing the sample.

| Component | Estimation input |
| --- | --- |
| AgenticOS ledger and BM25 | Zero model spend. Record local compute and database time separately. |
| Mem0 / Hindsight | Sum provider costs for extraction, embedding and recall for the pilot. Extrapolate by eligible session bytes and question count. Missing provider costs appear as unknown in the retrieval report. |
| Answer generation | `answer.py --estimate-only` reserves from request size and output cap. The usage log calculates actual input/output cost from provider-reported tokens. |
| Grading | One initial judging request per hypothesis, multiplied by the measured judge cost. The upstream judge manages its own retries and budget. |
| Human review and scale | Record engineer time and machine time separately. Review disputed, temporal and abstention cases even if average accuracy is high. |

## 5. Measure ledger scale

```sh
# From backend/ with the current disposable MEMORY_BENCH_AGENTICOS_DSN.
for ROWS in 10000 100000 1000000; do
  uv run python "$B/scale.py" --rows "$ROWS" --repetitions 50 \
    --out "$OUT/scale-$ROWS.json"
done
```

This uses the existing ledger SQL against synthetic rows in one scope, with deliberately
similar distractors. It records migration revision, load time, warm query samples,
p50/p95 and exact top-result misses. It stays in a rollback-only transaction and makes
zero model calls. Start at 10,000 rows and keep the database disposable. A single warm
query workload cannot establish concurrent throughput, index rebuild time or tenant
fairness. Those remain separate scale experiments.
