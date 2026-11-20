# AgenticOS local evaluations

The three suites share **150 synthetic multi-turn conversations** in [datasets/](datasets/). Run them from the CLI with the repository's locked dependencies. The runner creates no entries in the platform's Datasets or Evals views.

| Suite | Cases | Path exercised |
| --- | ---: | --- |
| AgenticOS | 50 | Published shipped starter, conversation history, tool routing and arguments, answers |
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
evals/personal/stack.sh up -d app worker sandboxd artifact-render
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

Without `--max-usd`, the command only checks the published AgenticOS and selected model. Omit `--limit` to select all 50 cases. This example checks three cases without making model calls:

```sh
evals/personal/stack.sh run --rm --no-deps -T app sh -c '
  exec /app/.venv/bin/python /personal-eval/run.py --suite agenticos \
    --organization-id "$AGENTICOS_EVAL_ORG_ID" --user-id "$AGENTICOS_EVAL_USER_ID" \
    --limit 3 --case natural-hello --case inbox-direct --case sandbox-file
'
```

### Run all 50 AgenticOS cases

```sh
mkdir -p evals/personal/results
report="evals/personal/results/$(date +%F-%H%M%S)-deepseek-v4-flash-0731-agenticos.jsonl"

evals/personal/stack.sh run --rm --no-deps -T app sh -c '
  exec /app/.venv/bin/python /personal-eval/run.py --suite agenticos \
    --organization-id "$AGENTICOS_EVAL_ORG_ID" --user-id "$AGENTICOS_EVAL_USER_ID" \
    --limit 50 --max-usd 1
' > "$report"
```

The terminal shows the current case, a heartbeat after each 15 seconds of waiting, the outcome, elapsed time and cost. The report receives one JSON line per completed case. An exit code of 1 means a failed check or an incomplete run. Check the summary for how many cases finished.

Use `--max-usd 0.25` with the preflight selection for a paid three-case smoke run. The runner passes the remaining budget into the production budget guard and stops when cost is incomplete. The platform uses its bundled price catalog when there is no verified provider cost. A provider key spend limit also covers pricing uncertainty and work outside this guard.

The trace runner starts each case in a fresh private test chat with the authored history. It scores the recorded tools, argument subsets and forbidden attempts before any judge call. The production isolation guard holds side-effecting actions. Use live probes to verify effects. Seed synthetic Inbox items, task state and connections for positive-path cases that need them.

## Background replay

From `backend/`:

```sh
uv run --env-file ../evals/personal/.env python ../evals/personal/run.py \
  --suite memory --model openrouter:deepseek/deepseek-v4-flash-0731 --limit 50 \
  > ../evals/personal/results/2026-11-20-deepseek-v4-flash-0731-memory.jsonl
uv run --env-file ../evals/personal/.env python ../evals/personal/run.py \
  --suite briefing --model openrouter:deepseek/deepseek-v4-flash-0731 --limit 50 \
  > ../evals/personal/results/2026-11-20-deepseek-v4-flash-0731-briefing.jsonl
```

Use repeated `--case` with `--limit 3` for a smoke run. These modes and the judge also accept other Pydantic AI model identifiers. Provider-reported USD is recorded when available.

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
    --judge-report "$1" --limit 50
' sh "../$report" > "${report%.jsonl}-judge.jsonl"
```

The judge grades only rows that passed deterministic checks. It evaluates an isolated write by the attempted action and what the answer claims happened. Live probes verify the actual effect. A judge provider or token-limit failure is recorded separately from a model verdict. Keep its model fixed across candidate comparisons and log its cost separately. Compare tool accuracy, judged correctness, cost per passing case, p50/p95 latency and incomplete-cost rows. The [design and cost assumptions](DESIGN.md) specify the initial model and expected spend.
