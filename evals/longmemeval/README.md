# LongMemEval

Status: upstream benchmark selected; no AgenticOS memory adapter is implemented
yet. This directory is separate from [AgentDojo](../agentdojo/README.md) and
[AppWorld](../appworld/README.md). It does not contain a fabricated score or a
runner that treats whole-context answering as a test of AgenticOS memory.

[LongMemEval](https://github.com/xiaowu0162/LongMemEval) evaluates answering from
long conversation histories. The released S, M and oracle variants answer
different questions: S has roughly 115k history tokens per question (tokenizer
dependent), M is longer, and oracle supplies only the evidence sessions.
Scores must name the variant, dataset revision, memory/retrieval system, answer
model, judge and all questions including failures.

Use the [cleaned dataset](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)
from a pinned revision outside the source tree. When implementing the adapter,
keep every question's memory isolated, ingest history chronologically, and never
expose `answer`, `answer_session_ids` or `has_answer` labels to the evaluated
agent. Export JSONL containing `question_id` and `hypothesis` for the upstream
`src/evaluation/evaluate_qa.py` scorer; that judge makes separate paid calls.
Do not silently substitute a home-grown judge for the official scoring protocol.

See [published results and budget assumptions](../comparison.md). No live
AgenticOS scores have been measured, and no dataset or model is invoked here.
