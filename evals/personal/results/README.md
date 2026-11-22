# Versioned local evaluation results

Keep each candidate run as `YYYY-MM-DD-model-suite.jsonl` with an optional matching `-judge.jsonl`. Add a revision suffix for repeated measurements. In review, record the commit tested, published starter version, provider and model ID, selected cases, fixture state, pricing and whether the run completed. Retain the baseline instead of replacing its file.

Each row records the synthetic case ID, candidate output, deterministic errors, available tool trace, tokens, latency and USD. A missing or partial cost is unknown. Judge reports are separate. A skipped case or interrupted run is missing evidence.

Commit only results from the disposable eval stack after reviewing traces for credentials, signed URLs, private data and machine-specific paths. Keep logs and environment files local.


The [2026-11-21 private-greeting candidate verification](2026-11-21-proactive-greeting-policy.md) records deterministic local checks and the completed seven-case native smoke (4/7, $0.153621), followed by unmeasured prompt fixes. It intentionally changes the historical no-tool greeting expectation; the earlier model scores remain attached to their own prompt versions.
