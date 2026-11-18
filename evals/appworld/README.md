# AppWorld

Status: upstream benchmark selected; no AgenticOS adapter is implemented yet.
The executable AgentDojo adapter is a different benchmark and lives in
[`../agentdojo/`](../agentdojo/README.md).

[AppWorld](https://github.com/StonyBrookNLP/appworld) evaluates multi-step work
across simulated everyday applications. Its state-based tests check task outcomes
and unintended changes. Use its official environment and task tests when adding
an adapter; do not replace them with keyword checks or claim AgentDojo scores
as AppWorld results. Pin the upstream revision, split, task IDs, tool interface,
prompt hash and budgets in any future report.

The upstream repository distinguishes public code from protected task/app data.
Keep data bundles in the form permitted by upstream; do not vendor decrypted
benchmark data into AgenticOS. No dataset or model calls are downloaded or run
by creating this directory.
