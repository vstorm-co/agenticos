# AgenticOS local evaluations

Three datasets contain **150 synthetic conversations**, with stable IDs and authored multi-turn context. The cases use no production data.

| Dataset | Cases | What it measures |
| --- | ---: | --- |
| Memory | 50 | Durable preferences, exact user evidence, new and superseded claims, paraphrase deduplication, ownership, and bounded transcripts |
| Daily briefing and suggestions | 50 | Distinct chats and days, recurring goals, existing routines, withdrawn or dismissed proposals, connected sources, and grounded profile or starter suggestions |
| AgenticOS | 50 | Direct responses, full-source reading, tool selection and arguments, memory, Tasks, Skills, Context, routines versus watches, delegation consent, Sandbox, charts, visuals and Apps |

`history.json` supplies extended histories. The runner validates and exports the production dataset schema. Each scenario grades an authored outcome. Expected answers and tool assertions stay outside the candidate's conversation.

## Run the local stack

From the repository root, copy `evals/personal/.env.example` to `evals/personal/.env`. Set a random `SANDBOXD_TOKEN` and an OpenRouter key with a dedicated spend limit. Compose scopes Postgres, Redis and media volumes to this project. The API is exposed only at `127.0.0.1:18080`. Sandboxd and the App render service use the same pinned definitions as the development platform.

```sh
mkdir -p /tmp/agenticos-personal-eval-workspaces
chmod 1777 /tmp/agenticos-personal-eval-workspaces
evals/personal/stack.sh build app
evals/personal/stack.sh up -d app worker sandboxd artifact-render
evals/personal/stack.sh ps
evals/personal/stack.sh exec -T app sh -c '
  BOOTSTRAP_API_KEY="$OPENROUTER_API_KEY" exec agenticos cmd bootstrap \
    --org "AgenticOS Local Eval" --provider openrouter --model moonshotai/kimi-k2.6
'
```

If you customize `SANDBOX_WORKSPACE_ROOT`, create that path on the Docker host and give the sandbox service access to it. The built image is shared by API, worker and migrations. Rebuild it after editing the starter. Browser use and computer use are outside the required suite. The headless renderer is used for App previews.

Use `POST /api/v1/auth/login` with the bootstrap account on this stack and export the returned access token as `AGENTICOS_EVAL_TOKEN`. Take the organization and published AgenticOS IDs from the test stack. Keep the tenant disposable with synthetic fixtures and unused mail or messaging destinations. Stop it with `evals/personal/stack.sh down` when done.

## Validate for free

```sh
cd backend
uv run python ../evals/personal/run.py --export /tmp/agenticos-personal
uv run python -m unittest discover -s ../evals/personal
uv run pytest -q tests/test_memory_claims_tools.py tests/test_memory_claim_mutations.py \
  tests/test_briefing.py tests/test_proactive.py tests/integration/test_proactivity.py \
  tests/integration/test_memory_runtime.py tests/integration/test_shipped_agents.py
```

The integration tests verify actual memory storage, scope and correction. They also verify proposal persistence and morning briefing delivery. Morning delivery has no model call. It consumes eligible, unbriefed findings and marks them delivered, so the next sweep skips them.

## Measure candidate behavior without a judge

For a background replay, load credentials from the dedicated env file. Examples from `backend/`:

```sh
uv run --env-file ../evals/personal/.env python ../evals/personal/run.py \
  --suite memory --model openrouter:deepseek/deepseek-v3.2 --limit 3 \
  --case changed-hours --case already-brief --case long-audit > memory.jsonl
uv run --env-file ../evals/personal/.env python ../evals/personal/run.py \
  --suite briefing --model openrouter:z-ai/glm-5.1 --limit 3 \
  --case release-notion --case dismissed-notion --case role-from-claim > briefing.jsonl
```

These replays call the production model instructions and schemas with test packets. They evaluate model extraction and proposals while leaving application state alone. The checks cover evidence provenance, expected changes, repeated intent, duplicate proposals and unsupported profile claims. The run logs tokens, latency and provider-reported USD when available. Missing cost is recorded as `null`.

For AgenticOS, create a native dataset with deterministic scoring and **disable its native judge**. Append the corpus with `--suite agenticos --import-into "$DATASET_ID"`, then pin the imported version. Seed any positive-path Inbox, memory, connection and task fixtures inside this eval workspace. Cases without those fixtures can still test how the agent handles missing resources, but cannot validate the corresponding positive-path output.

```sh
uv run python ../evals/personal/run.py --api-url http://127.0.0.1:18080 \
  --organization-id "$ORG_ID" --agent-id "$AGENT_ID" --dataset-id "$DATASET_ID" \
  --dataset-version "$DATASET_VERSION" --model-profile "$MODEL_PROFILE_ID"
```

Repeat with `--max-usd 1` to submit if the estimate and budget permit it. The estimate is an admission threshold. Set a spend limit on the API key for a provider-side cap. Repeat `--model-profile` to compare several deployed profiles on identical cases. Once the worker finishes, get the actual evidence:

```sh
uv run python ../evals/personal/run.py --api-url http://127.0.0.1:18080 \
  --organization-id "$ORG_ID" --report-run "$RUN_ID" > agenticos.jsonl
```

The report checks expected tool names and argument subsets, forbidden attempts and completion. It distinguishes executed, blocked, replayed and divergent calls. A blocked write may meet the trajectory expectation, but cannot demonstrate its effect. Use separate live probes for those effects.

## Check real local effects

The live commands use disposable chats in the eval tenant. The four tool probes use fixed synthetic inputs and expect completed Sandbox, chart, visual and private App operations. App output needs an actual renderer preview. The memory probe uses three distinct conversations and the claims API to verify a new preference, a superseding correction and subsequent recall.

```sh
uv run python ../evals/personal/run.py --api-url http://127.0.0.1:18080 \
  --organization-id "$ORG_ID" --agent-id "$AGENT_ID" --limit 4 \
  --live-case sandbox-file --live-case report-chart-real \
  --live-case diagram-approval --live-case app-private-preview > live-tools.jsonl
uv run python ../evals/personal/run.py --api-url http://127.0.0.1:18080 \
  --organization-id "$ORG_ID" --agent-id "$AGENT_ID" \
  --limit 3 --live-memory > live-memory.jsonl
```

The runner leaves real approvals in place. Unexpected approval, refusal or failed execution stays visible in the report. The live probe uses the model pinned to the agent's published version.

## Apply an optional LLM judge

```sh
uv run --env-file ../evals/personal/.env python ../evals/personal/run.py \
  --judge-model 'openrouter:<judge-model-id>' --judge-report agenticos.jsonl \
  --limit 10 > judgments.jsonl
```

The judge uses Pydantic AI structured output and sees only cases that passed deterministic checks. It checks correctness, proportional brevity, supported claims and honesty about actual tool outcomes. It logs its own spend, tokens and latency separately. Keep the same judge and evidence limits across candidate runs. The background and judge runners also accept other Pydantic AI model identifiers with their provider's credentials.

Use fixed versions, selected cases and fixture state for comparisons. Suggested candidate profiles are [Kimi K2.6](https://openrouter.ai/moonshotai/kimi-k2.6), [DeepSeek V3.2](https://openrouter.ai/deepseek/deepseek-v3.2) and [GLM 5.1](https://openrouter.ai/z-ai/glm-5.1). Compare tool accuracy, correctness, cost per pass and p50/p95 latency against a pinned Sonnet or Opus baseline before choosing a replacement. Rates and routing may change.
