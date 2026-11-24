# Channel history and research follow-ups

The isolated Docker runner exercised four new AgenticOS cases plus a greeting,
using the shipped AgenticOS instructions with DeepSeek V4 Flash 0731 on OpenRouter.
Deterministic checks ran before GLM-5.3 judged the answers. The full three-suite
benchmark is recorded in [the preceding report](2026-11-20-personal-benchmark-rerun.md).

| Case | Deterministic | Judge | Tool calls | Time | Model cost |
| --- | --- | --- | ---: | ---: | ---: |
| Greeting | Pass | Pass | 0 | 6.1 s | $0.00172 |
| Full paper follow-up | Pass | Pass | 6 | 138.6 s | $0.04646 |
| Vendor pricing follow-up | Pass | Pass | 1 | 10.6 s | $0.00390 |
| Mattermost history replay | Pass | Pass | 0 | 4.3 s | $0.00200 |
| Slack history replay | Pass | Pass | 0 | 6.0 s | $0.00230 |

The initial verification passed 5/5 deterministic checks and 5/5 judge checks.
Recorded spend was $0.05638 for the model and $0.00511 for the judge. Total case
time was 165.6 seconds for the model and 13.2 seconds for the judge.

The full paper case read six consecutive `web_fetch` pages, starting at offsets
0, 40,000, 80,000, 120,000, 160,000 and 200,000. The final result returned
`next_offset: null`. The answer cited the requested appendix and table. The first
attempt before pagination took 150.3 seconds, used 24 tool calls, cost $0.11083,
and did not complete the full read. The pricing follow-up provided official vendor
evidence to the judge and used one fetch.

The simulated group conversations used the channel history adapter and synthetic
messages stored with Mira's and Teo's identities. Both preserved the completed read
and two updates without repeating them. Both identified a missing URL in the
available history. The fixtures use no real Mattermost or Slack account.

The first Slack answer also printed shortened synthetic user IDs. The channel
guidance now asks for nicknames or display names in replies and the scorer checks
for raw fixture IDs. A second pass through both channels used the production
exposure prompt. It passed 2/2 deterministic and 2/2 judge checks. Neither answer
printed an internal ID or made a tool call. Recorded spend was $0.00437 for the
model and $0.00045 for the judge. Total case time was 18.4 and 3.1 seconds,
respectively.
