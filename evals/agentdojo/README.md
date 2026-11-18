# AgentDojo

[AgentDojo](https://github.com/ethz-spylab/agentdojo) supplies simulated workspace
tools, tasks and state-based utility checks. Our adapter runs the shipped prompt
through Pydantic AI while retaining those upstream tasks and scorers. It starts
with **two workspace tasks**, not the full benchmark, and performs **no injection
attacks**. Report the task IDs, package version, benchmark version and prompt hash
with any result. Do not describe this subset as an official leaderboard score,
a platform integration test or a prompt-injection safety score.

The optional package is isolated to this eval invocation; it is not an application
dependency and does not change the lockfile. The adapter requires `agentdojo==0.1.35`
and benchmark `v1.2.2`. The eval-only DeepDiff pin avoids pulling its newer
compiled cache dependency into the application’s Python environment. Its plan works without installing the optional dependency:

```sh
uv run python ../evals/agentdojo/run.py
uv run --with agentdojo==0.1.35 --with deepdiff==8.6.1 python ../evals/agentdojo/run.py \
  --run --model <provider:model> --task user_task_0 \
  --output /tmp/assistant-agentdojo.json
```

Each task has a ceiling of 20 model requests, 30 tool calls and 100,000 total
tokens. At most ten explicit task IDs may be selected per invocation. Use a
provider spending cap for a monetary limit. Failures stay in the denominator;
errors are recorded by class without provider exception text or credentials.
No live scores have been measured as part of the offline test suite.

Upstream reference: [AgentDojo paper](https://arxiv.org/abs/2406.13352),
[usage and API](https://agentdojo.spylab.ai/),
[MIT license](https://github.com/ethz-spylab/agentdojo/blob/main/LICENSE).
The adapter is original code; upstream datasets and implementation are installed
from the pinned package, not copied into this repository.
