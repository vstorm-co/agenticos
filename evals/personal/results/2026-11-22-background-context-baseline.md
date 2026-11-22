# Background contract baseline and richer-context fixtures

The existing background suites were replayed on 2026-11-22 with the configured
`OpenRouter · anthropic/claude-sonnet-5.5` profile through its existing authenticated
gateway. The background runner accepted the resolved Pydantic AI model; the
production instructions and output schemas were unchanged. These were synthetic,
no-tool reads, not agent runs that created resources or delivered Inbox cards.

| Suite | Completed | Deterministic checks passed | Input tokens | Output tokens | Reported cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| Briefing/suggestions | 50/50 | 50 | 209,367 | 9,140 | $0.5611474 |
| Memory extraction | 50/50 | 50 | 97,543 | 4,148 | $0.2602226 |

No completed case had missing cost. The values are the gateway-reported model
usage/cost, not a separate provider invoice audit. Raw JSONL and console logs
remain outside Git. A deterministic pass verifies the authored contract and
scorer, not comprehensive personal-assistance quality or successful persistence.
The 122-case AgenticOS runtime suite was not rerun as part of this background pass.

The original briefing contract uses four authored requests, expects three
independent recurrence evidence IDs and returns `NightlyReading`. It does not
establish behavior for real weekly patterns spread across windows, actual task
state, tool effects or feature discovery. A perfect score on those 50 cases does
not answer the broader product question.

`datasets/context.jsonl` therefore adds 32 synthetic desired-behavior packets:
24 proactive-assistance cases and 8 memory cases, including 20 holdout cases.
They use the platform's `DatasetCaseContent` format with explicit references and
counter-examples. `context_cases.py` validates their payloads and source/case
identities through the production Dataset importer and can export the same JSONL.
They are not silently counted as passes for the old background schema and have
not received a paid semantic score in this report.

Deterministic verification: all original corpora validate (122 + 50 + 50), the
32 context packets import/export without dropping a case, and 37 runner/context
unit checks pass. The new resolved-model check uses a `FunctionModel`, not a
provider call. Real private conversation analysis and prototype extraction trials
are separate exploratory evidence and are not copied into this synthetic corpus.
