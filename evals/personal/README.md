# AgenticOS local evaluations

The three suites contain **222 synthetic multi-turn conversations** in [datasets/](datasets/). Run them from the CLI with the repository's locked dependencies. The runner creates no entries in the platform's Datasets or Evals views.

| Suite | Cases | Path exercised |
| --- | ---: | --- |
| AgenticOS | 122 | Published shipped starter, conversation history, scope, tool routing and arguments, answers |
| Memory | 50 | Production extraction model, durable facts, corrections, provenance, duplicate intent |
| Briefing and suggestions | 50 | Production nightly reading model, recurring intent, connected sources and existing or dismissed proposals |

The background suites exercise their production instructions and output schemas using synthetic packets. Database-level tests separately cover persistence, supersession and scope, and morning inbox delivery. The morning delivery pass does not call a model.

## Validate without spending

Run commands from the checkout containing this README. If you use several worktrees, switch to the one with `evals/personal/stack.sh` and its own `evals/personal/.env`. Check the current checkout with `git rev-parse --show-toplevel`.

From that repository root:

```sh
make eval-personal
cd backend
uv run python -m unittest discover -s ../evals/personal
```

Validation checks all three corpora. `--export /tmp/agenticos-personal` writes portable JSONL files locally.

## Run AgenticOS in Docker

Copy `evals/personal/.env.example` to `evals/personal/.env`. Use a dedicated OpenRouter key with a spend limit and a random `SANDBOXD_TOKEN`. Use test fixtures and unused messaging destinations. The stack uses separate database, Redis and media volumes and binds its API to loopback at port 18080.

```sh
mkdir -p /tmp/agenticos-personal-eval-workspaces
chmod 1777 /tmp/agenticos-personal-eval-workspaces
evals/personal/stack.sh build app
evals/personal/stack.sh up -d app worker sandboxd artifact-render eval-notion
evals/personal/stack.sh exec -T app sh -c '
  BOOTSTRAP_API_KEY="$OPENROUTER_API_KEY" exec agenticos cmd bootstrap \
    --org "AgenticOS Local Eval DeepSeek Baseline" --provider openrouter --model "$AGENTICOS_EVAL_MODEL"
'
```

Bootstrap installs AgenticOS and its dependencies through the production shipped-template path. It preserves an existing installation, including the previous model. For a clean comparison, use a fresh eval database or explicitly configure an eval model profile and pass its ID with `--model-profile`. Rebuild the Docker image after changing backend code or bundled resources. The preflight refuses a published starter whose managed configuration differs from the image. Start clean to get the current bundled Skill and Context contents as well.

Read the organization and user IDs from the eval database. Copy the two values, separated by `|`, into `AGENTICOS_EVAL_ORG_ID` and `AGENTICOS_EVAL_USER_ID` in `evals/personal/.env`:

```sh
evals/personal/stack.sh exec -T db sh -c '
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"
' -- "SELECT o.id, u.id FROM organizations o
JOIN organization_members m ON m.organization_id = o.id
JOIN users u ON u.id = m.user_id
WHERE o.slug = 'agenticos-local-eval-deepseek-baseline' AND u.email = 'admin@example.com'"
```

Without `--max-usd`, the command only checks the published AgenticOS and selected model. Omit `--limit` to select every case. This example checks three cases without making model calls:

```sh
evals/personal/stack.sh run --rm --no-deps -T app sh -c '
  exec /app/.venv/bin/python /personal-eval/run.py --suite agenticos \
    --organization-id "$AGENTICOS_EVAL_ORG_ID" --user-id "$AGENTICOS_EVAL_USER_ID" \
    --limit 3 --case natural-hello --case inbox-direct --case sandbox-file
'
```

### An unpublished prompt candidate in an isolated local database

`--candidate-agent <agent UUID>` explicitly selects an existing published agent's bindings and replaces only its instructions in memory with the bundled AgenticOS starter. It validates the candidate against the caller's access and uses the existing `UnpublishedCandidate` execution path. It does not install shipped resources, save a draft, change the agent's selected model or publish a version. Omit this flag to retain the managed-starter publication/review guard described above.

Use this mode only with an explicitly isolated QA database. Set `AGENTICOS_PERSONAL_EVAL=1` and the target `POSTGRES_DB` in the command's environment while keeping the normal backend configuration local. Provide `--suite agenticos`, `--organization-id`, `--user-id`, `--candidate-agent`, and an authorized `--model-profile` override. Without `--max-usd`, the runner only performs the free preflight. Add `--max-usd 0.25` only for an approved paid smoke; the same remaining-budget and incomplete-cost safeguards apply. This mode still records synthetic conversations, run receipts and metered spend in the selected test database.

If a source browser endpoint cannot pass deployment validation, the explicit QA-only `--candidate-without-browser` flag removes only `browser_use` from the in-memory candidate. It requires `--candidate-agent`; it does not change the allowlist or saved bindings. Receipts include the exact omitted capabilities and full candidate spec hash. Such a run cannot establish equivalence to the full published agent.

Candidate results have no published `agent_version`. They record `source_agent_version` and `candidate_instructions_hash` instead, so changed instructions cannot receive credit as the existing publication. Retain the report outside the repository until its outputs have been reviewed for private data. A named QA model profile can use an existing authorized vault reference without changing any agent's model or printing the secret; profile creation is a separate explicit setup write, never performed by the runner.

### Run all AgenticOS cases

```sh
mkdir -p evals/personal/results
report="evals/personal/results/$(date +%F-%H%M%S)-deepseek-v4-flash-0731-agenticos.jsonl"

evals/personal/stack.sh run --rm --no-deps -T app sh -c '
  exec /app/.venv/bin/python /personal-eval/run.py --suite agenticos \
    --organization-id "$AGENTICOS_EVAL_ORG_ID" --user-id "$AGENTICOS_EVAL_USER_ID" \
    --max-usd 2
' > "$report"
```

The terminal shows the current case, a heartbeat after each 15 seconds of waiting, the outcome, elapsed time and cost. The report receives one JSON line per completed case. An exit code of 1 means a failed check or an incomplete run. Check the summary for how many cases finished.

A failed agent run recorded by the backend, such as a sandbox permission refusal, produces a technical failure row with its known cost. The runner continues with the remaining budget and stops if it cannot account for the failed run's spend.

Use `--max-usd 0.25` with the preflight selection for a paid three-case smoke run. The runner passes the remaining budget into the production budget guard and stops when cost is incomplete. The platform uses its bundled price catalog when there is no verified provider cost. A provider key spend limit also covers pricing uncertainty and work outside this guard.

The trace runner starts each case in a fresh private test chat with the authored history. It scores the recorded tools, argument subsets and forbidden attempts before any judge call. The production isolation guard holds side-effecting actions. Use live probes to verify effects. The Notion watch case uses the local, read-only `eval-notion` MCP service. The runner connects it as a synthetic personal account for that case and removes the connection after the case. The separate published watch agent has only that fixture binding. Watch creation remains an isolated tool attempt. Seed synthetic Inbox items, task state and other connections for positive-path cases that need them.

The 60 appended cases cover product choices, exact resource reads, approval boundaries, and ordinary requests. A synthetic resource ID tests routing to the correct reader and an honest unavailable result. Populate a matching resource separately to test a successful read against real state. The arguments column accepts a JSON object when a check needs numbers, booleans, arrays or nested values.

The greeting policy cases deliberately replace the earlier strict no-tool `natural-hello` expectation. The first private greeting reads existing private boards; it offers rather than provisions. `natural-hello`, `hello-empty-board` and `hello-priorities` use controlled read-only `TaskService` responses for the selected eval account and organization. Other subjects and table IDs fall through to the real service. These fixtures make board states reproducible without creating or deleting tasks; they test model routing through the authenticated MCP path, not database access enforcement. Read-only fixture overrides are restored after each case.

`hello-no-tools`, `hello-repeat` and `hello-shared-channel` require zero tool calls. They also hold an absent-board read fixture as a safety net: a violating lookup fails scoring without reading actual personal tasks. The channel case uses the production Slack group-history adapter without seeding the historical private tool calls used by the separate recall cases. Research and news cases check one structured Table or Routine proposal, while explicit one-off/no-tool requests keep initiative quiet. Proposal text still needs qualitative review; deterministic checks alone do not establish its usefulness or answer-first ordering.

`table-query-exact` creates a private scratch table with six pending vendors and one approved vendor. The runner substitutes the real table ID into the conversation and checks the equality filter and five-record first page. It archives the table after the case.

`mattermost-room-recall` and `slack-room-recall` simulate two named participants and a previous tool-backed turn. They exercise the production channel history path against persisted synthetic messages and tool records. They require no channel account or external message delivery. The two research follow-up cases cover full-paper reading and source-based vendor pricing.

## Background replay

Run from the repository root with the configured `evals/personal/.env`.

```sh
for suite in memory briefing; do
  report="evals/personal/results/$(date +%F-%H%M%S)-deepseek-v4-flash-0731-$suite.jsonl"
  uv run --directory backend --env-file ../evals/personal/.env sh -c '
    exec python ../evals/personal/run.py --suite "$1" \
      --model "openrouter:$AGENTICOS_EVAL_MODEL" --limit 50
  ' sh "$suite" > "$report"
done
```

Use repeated `--case` with `--limit 3` for a smoke run. These modes and the judge also accept other Pydantic AI model identifiers. Provider-reported USD is recorded when available.

Briefing uses the same proposal selection as production for duplicates, connected sources and usable schedules. The JSONL retains the model's proposals for diagnosis. Memory validates quoted evidence against the supplied user turns.

Each background case allows two requests, with a target cap of 3,072 output tokens per response and a run limit of 6,144 output tokens. The runner requests low thinking where supported. If a case exceeds its limit, retries an invalid output unsuccessfully, or hits a transient provider error, the JSONL records a technical failure, any available usage, and partial cost. The remaining cases still run. Authentication, billing, permission and missing-model errors stop the suite. A completed suite with failures exits nonzero.

## Live probes

Live probes use the published starter on the isolated stack. Set `AGENTICOS_EVAL_TOKEN` to a test account's access token, `AGENT_ID` to the published starter ID and `ORG_ID` to the organization ID saved in `.env`. Run from `backend/`:

```sh
uv run python ../evals/personal/run.py --api-url http://127.0.0.1:18080 \
  --organization-id "$ORG_ID" --agent-id "$AGENT_ID" --limit 4 \
  --live-case sandbox-file --live-case report-chart-real \
  --live-case diagram-approval --live-case app-private-preview
uv run python ../evals/personal/run.py --api-url http://127.0.0.1:18080 \
  --organization-id "$ORG_ID" --agent-id "$AGENT_ID" --limit 3 --live-memory
```

These verify actual Sandbox, chart, visual and private App outputs and write, correct and recall a synthetic preference across three conversations. Approval gates are active. Browser use and computer use are outside the suite. App preview uses the headless artifact renderer. Stop the stack with `evals/personal/stack.sh down`.

## Optional judge

From the repository root, after inspecting the deterministic report, keep the `report` variable from the AgenticOS command or set it to that report's path relative to the root.

```sh
uv run --directory backend --env-file ../evals/personal/.env sh -c '
  exec python ../evals/personal/run.py --judge-model "$AGENTICOS_EVAL_JUDGE_MODEL" \
    --judge-report "$1" --limit 122
' sh "../$report" > "${report%.jsonl}-judge.jsonl"
```

The judge grades only rows that passed deterministic checks. It evaluates an isolated write by the attempted action and what the answer claims happened. Live probes verify the actual effect. A judge provider or token-limit failure is recorded separately from a model verdict. Keep its model fixed across candidate comparisons and log its cost separately. Compare tool accuracy, judged correctness, cost per passing case, p50/p95 latency and incomplete-cost rows. The [design and cost assumptions](DESIGN.md) specify the initial model and expected spend.

## Richer context regression packets

`datasets/context.jsonl` adds **51 synthetic cases**: 40 for proactive assistance
and 11 for memory. They cover weekly/monthly cycles, high activity, important text
after the old clip, changed task state without a new chat, tool receipts, shared
responsibility, feature availability and usage, memory corrections and erasure.
Three appended training cases supply explicit conversation links and an existing
routine for native answers/corrections, and a memory reference aligned with the
writer's durable-fact contract. The original 44 packets remain unchanged: two
native-answer references lack a question-to-conversation link or an identifiable
job, and one asks for assignment expiry unsupported by that writer. Report their
raw results and this fixture audit separately; do not silently relabel failures.
A further training case reproduces a human automation request with authenticated
answers followed by an assistant creation claim, while the complete current
routine list is empty. It expects new setup with the known choices, not attention
to a fabricated paused resource; the explicit-deletion case remains separate.

The additional adversarial cases cover authenticated Ask user answers, corrections,
deleted routines, citations that do not support a claim, incomplete resource pages,
revoked cached evidence, expired questions and timezone-aware schedules.
Thirty-two cases are marked `holdout`. Their labels remain useful for reporting, but cases inspected during implementation are no longer an unseen holdout. Report that exposure rather than claiming independent validation.

These are desired-behavior fixtures, not another 51 successes for the older
`NightlyReading` schema. Their references and counter-examples need semantic
review. The existing 222-case corpus and its scores remain separate. The packets
use the platform's `DatasetCaseContent` JSONL format, so the normal Dataset import
and evaluation path can consume them. `run.py` remains the older narrow-contract
replay. `context_run.py` compares that reader with the production context pipeline
and memory transcript selection.

```sh
cd backend
uv run python ../evals/personal/context_cases.py
uv run python ../evals/personal/context_cases.py --export /tmp/context-cases.jsonl
uv run python -m unittest discover -s ../evals/personal
```

The validator uses the production importer and checks unique case/source IDs,
partitions, target components and typed context packets. It makes no model calls.
Private conversation exports, prompts and raw reports belong outside Git. Add
synthetic regressions for the observed failure instead of committing a user's
history.

The Python background runner also accepts a resolved Pydantic AI `Model` and an
explicit `model_label`. This preserves a configured authenticated gateway without
copying credentials into report files or silently switching to a public endpoint.
Its CLI model-name behavior is unchanged.


### Paired context replay

From the repository root, choose the model explicitly:

```sh
uv run --directory backend python ../evals/personal/context_run.py \
  --model "openrouter:YOUR_CONFIGURED_MODEL" \
  --report /tmp/context-paired.jsonl --max-usd 3
```

Use repeated `--case <case-id>` for a focused replay. Python callers can pass a
resolved Pydantic AI `Model` to `run_context` to retain a deployment's configured
gateway. Keep credentials in that deployment; never copy them into a report.

The new path indexes each conversation separately in 16,000-character segments,
uses the production citation and ownership checks, proposes up to four cards and
independently verifies cards and starters. The replay does not mutate product
resources or activate proposed work. Current database authorization, checkpoint
persistence, erasure, resumption and unchanged-read behavior are covered separately
by `tests/integration/test_personal_context_cache.py`.

Every model request, repair and judge call records its output, usage, latency and
provider-reported cost. The explicit USD limit stops admission after known spend
reaches it; one admitted request can exceed the remaining amount. Missing cost
information stops the replay. Preserve failed attempts when calculating total
spend. A model judge is an aid to review, not a human usefulness rating. Report
technical failures separately, and do not merge these scores with the original
222-case corpus.

Temporal-context regressions include Polish and German scheduling answers in words and a message timestamp with unselected time options. Extraction and verification receive original event timestamps, local UTC offsets and linked structured questions/answers. The model interprets scheduling intent; code validates source identities, exact citations and access rather than parsing natural-language weekdays or hours. Memory maintenance retains source timestamps and distinguishes native questions from submitted human answers.
