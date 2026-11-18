# AgenticOS assistant evaluations

These authored smoke cases use the current `general/agenticos` template. They do not
contact a deployment, a personal coding account or real external tools. Running
without `--run` prints the selected cases, prompt fingerprint and zero model calls.
A model is always chosen explicitly; these commands do not change application defaults.

From `backend/`, using the repository's locked environment:

```sh
uv run python ../evals/assistant/run.py
uv run python ../evals/assistant/run.py --run --model <provider:model> \
  --case casual-polish-greeting --output /tmp/assistant-smoke.json
```

Configure that provider through its normal environment variables. Do not commit
keys, private prompts or reports containing private data. Cases run serially with
six requests and 30,000 total tokens per case at most. Token checks can stop only
after a model response; they are not a dollar budget. Start with one case.

`cases.json` covers a casual Polish greeting, economical direct answers, one safe
read retry, inspecting an uncertain send, ignoring instructions in web content
and keeping named coding sessions on the requested accounts. The verdicts are
explicit checks of text and recorded mock-tool calls. They do not prove general
answer quality or real container isolation. Backend integration tests cover the
latter. `backend/tests/test_assistant_eval.py` exercises scoring and a fake model
without paid calls, so ordinary CI stays deterministic.

Established benchmarks live separately: [AgentDojo](../agentdojo/README.md),
[AppWorld](../appworld/README.md) and [LongMemEval](../longmemeval/README.md).
