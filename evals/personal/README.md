# Personal assistant evaluation

The corpus contains 100 synthetic conversations. No data was copied from a personal or production workspace.

| Dataset | Cases | What the runner checks |
| --- | ---: | --- |
| Memory | 40 | Durable claims, exact user evidence, same-subject corrections, paraphrase deduplication, refusals and bounded long inputs |
| Daily briefing and suggestions | 30 | Separate chats and days, a repeated goal, existing routines and proposal history, connected sources, profile evidence and starter deduplication |
| AgenticOS | 30 | Inbox, tasks and scopes, recall, workflows, watches versus routines, web routing, preferences and concise Polish answers |

The pipe-delimited files keep the original messages and expected behavior together. `history.json` holds longer prefixes. Each case has a stable ID. The histories are supplied to the model without the expected answer. Inputs use synthetic names and IDs. For the AgenticOS native eval, seed any referenced Inbox card, task board, connections, or memory in a dedicated test workspace if the case should exercise the available-resource path. The native runner isolates tools and reports attempted and blocked calls. Actual persistence and cross-chat retrieval also need a runtime integration test.

## Free validation and integration checks

From the repository root:

```sh
uv run --directory backend python ../evals/personal/run.py
uv run --directory backend python ../evals/personal/run.py --export /tmp/personal-evals
```

Export uses the repository's JSONL import contract. The three files can be imported under **Datasets** or appended to a dedicated dataset with `--api-url URL --suite SUITE --import-into DATASET_UUID`. For the chat suite, enable the trajectory scorer and a judge that grades against each case's reference answer. The report also checks forbidden tool attempts from the actual trace, including attempts blocked by eval isolation.

Use the existing persistence tests alongside the corpus. They cover actual memory writes and read scope, persisted proposals, briefing delivery, and retry deduplication against the production paths:

```sh
cd backend
uv run pytest -q tests/test_memory_claims_tools.py tests/test_memory_claim_mutations.py \
  tests/test_briefing.py tests/test_proactive.py tests/integration/test_proactivity.py \
  tests/integration/test_system_agents.py
```

## Run a background prompt against a model

An explicit model and case limit are required. Use provider credentials already configured in the shell. The prompt replay uses the current production instructions and output schemas. It does not write application state or schedule a task. It reports model requests and input/output tokens per case, and exits nonzero on failed checks.

```sh
uv run --directory backend python ../evals/personal/run.py --suite memory \
  --model '<provider:model>' --limit 3 \
  --case changed-hours --case already-brief --case long-audit
uv run --directory backend python ../evals/personal/run.py --suite briefing \
  --model '<provider:model>' --limit 3 \
  --case release-notion --case dismissed-notion --case role-from-claim
```

The morning briefing delivery itself does not call a model. Its integration checks verify that pending unbriefed findings are announced once and are not sent again.

## Run the published AgenticOS agent

Import `agenticos.jsonl`. Set `AGENTICOS_EVAL_TOKEN` to a test workspace member access token (JWT). Use `--organization-id` to select the workspace. Pin the imported dataset version. The first command returns the platform estimate and does not submit a run. Add `--max-usd <ceiling>` to submit only if grading covers every case and the recorded estimate fits the ceiling and platform budgets. Provider spend is measured after execution, and the estimate is not a hard provider spend cap.

```sh
uv run --directory backend python ../evals/personal/run.py \
  --api-url http://127.0.0.1:8028 --agent-id '<agent UUID>' \
  --dataset-id '<dataset UUID>' --dataset-version 2
uv run --directory backend python ../evals/personal/run.py \
  --api-url http://127.0.0.1:8028 --report-run '<eval run UUID>'
```

Keep model, dataset version, fixture state, and selected case IDs fixed when comparing before and after. Compare duplicate and unsupported writes separately from missed durable facts. For cost tuning, compare input/output tokens and spend per useful new fact or proposal.
