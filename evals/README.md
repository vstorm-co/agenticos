# Agent evaluations

Keep authored smoke checks and each upstream benchmark separate.

| Directory | Purpose | Current status |
| --- | --- | --- |
| [assistant](assistant/README.md) | Shipped prompt behavior with controlled mock tools | Runnable; offline tests only |
| [agentdojo](agentdojo/README.md) | Upstream workspace task utility | Runnable; two tasks by default, no injection attacks |
| [appworld](appworld/README.md) | Multi-application task completion | Adapter not implemented |
| [longmemeval](longmemeval/README.md) | Long-term conversational memory | Adapter not implemented |
| retrieval | Documentation retrieval | Existing independent harness |

[Published model results and cost scenarios](comparison.md) distinguish external
systems' measurements from unmeasured AgenticOS results. Optional benchmark
packages do not become application dependencies. Run no paid measurements until
the maintainer chooses a model and budget.
