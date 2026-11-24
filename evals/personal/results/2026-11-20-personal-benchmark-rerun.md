# Personal benchmark rerun on DeepSeek V4 Flash 0731

This compares the full 17:04 rerun against the previous full set for each benchmark. Accuracy comes from the runner's deterministic checks. Latency is measured per case and p95 uses the nearest rank. Total case time sums measured durations and excludes gaps between commands. The former AgenticOS total includes the failed case recovered from the database and the continuation. Costs are known recorded USD.

| Suite | Passes and accuracy | Known cost | Median time | p95 time | Total case time |
| --- | --- | --- | --- | --- | --- |
| AgenticOS | 101/110 (91.8%) → 106/110 (96.4%) | $1.71070 → $0.89374 | 17.88 s → 14.21 s | 92.32 s → 91.54 s | 67m 56s → 42m 35s |
| Memory | 48/50 (96%) → 49/50 (98%) | $0.01059 → $0.00789 | 2.77 s → 3.25 s | 10.67 s → 6.63 s | 3m 12s → 2m 56s |
| Briefing & Suggestions | 42/50 (84%) → 48/50 (96%) | $0.02456 → $0.01821 | 6.17 s → 5.62 s | 18.53 s → 13.07 s | 6m 34s → 5m 10s |
| **All suites** | **191/210 (91.0%) → 203/210 (96.7%)** | **$1.74585 → $0.91983** | | | |

Briefing cost is incomplete for three previous cases and one current case. The three suites all finished. The new AgenticOS run recorded 110/110 cases in a single process and had no technical failures.

## What changed in the full rerun

- **AgenticOS.** All nine previous failures passed: watch setup, context reuse and creation, the run payload window, skill inspection, task change, artifact source, sandbox policy and capability details. Some of the cases now check corrected tool contracts, including safe handling of a missing task and reading editable App source. `sandbox-policy-by-connection` used the policy reader and finished in 14.7 seconds. The next cases ran normally. The file-write case passed with `write_file` inside isolation. The separate refusal regression test simulates a denied read and checks that a charged failure row is written before the next case. The watch attempted the scoped, change-only operation. `new-connection` took 8.3 seconds and $0.00549 with two calls and no delegation, down from 632.4 seconds, $0.16428 and 46 calls.
- **Memory.** `chosen-oncall` and `decision-rolled-back` passed. `one-off-brief` recurred. The model retained constraints about a one-line status update and the relationship between two documents.
- **Briefing & Suggestions.** All eight former failures passed. `role-already-filled` returned `UnexpectedModelBehavior` and the suite continued. The replay did not capture a model output for this case. `fuzzy-dismissal` repeated a dismissed Notion audit under a paraphrased title.

## Follow-up for this run

The remaining AgenticOS failures concerned unresolved task scope (`multi-scope`), public fetching while checking private Knowledge setup (`knowledge-no-published-copy`), the typed table query blocked by a missing fixture (`table-query-exact`), and personal MCP tool inventory (`connection-tool-schema`). The follow-up requires the agent to end the turn after asking about scope, keeps private Knowledge inventory inside the platform, seeds a private vendor register for the typed filter and page test, and identifies the exact connection inventory operation.

Memory now requires explicit evidence of standing relevance before retaining one-off output and document details. Briefing compares dismissed proposals by underlying work and makes the rules for an already populated profile explicit.

The scores above are from the full rerun. Follow-up results are from selected cases and do not replace those scores.

| Follow-up | Verified on DeepSeek |
| --- | --- |
| AgenticOS | All four cases passed across targeted runs. The table check initially found an off-by-one page size, then passed with the explicit five-record query and pagination fixture. |
| Memory | 5/5, including `one-off-brief`, its previous failure cases, and checks for project role and working hours. |
| Briefing & Suggestions | 3/3, including both new failures and the distinct CI sources case. |

The local suite also passed 120 backend tests and 21 runner tests. The corpus validator loaded all 210 cases.
