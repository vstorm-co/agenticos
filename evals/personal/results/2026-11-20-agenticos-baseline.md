# AgenticOS baseline · 2026-11-20

The isolated candidate run used commit `44e3c64ee`, published AgenticOS version `76c4f4fa-ac06-4943-908a-f7612f819570`, and OpenRouter `deepseek/deepseek-v4-flash-0731`. All 50 cases completed. The candidate and judge JSONL files are local. This report records the denominators and the failures without copying transcripts.

| Stage | Passed | Known cost | Input tokens | Output tokens | p50 | p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Candidate deterministic checks | 45/50 (90.0%) | $0.59621 | 4,979,416 | 135,952 | 17.70 s | 96.01 s |
| First complete GLM 5.3 judge pass | 39/45 (86.7%) | $0.05033 | 47,274 | 6,048 | 1.59 s | 4.50 s |
| GLM 5.3 with revised grading instructions | 40/45 (88.9%) | $0.04520 | 50,098 | 6,831 | 1.82 s | 5.71 s |

The candidate took about 25 minutes. The revised judge took 106 seconds. p95 uses the nearest rank. The pipeline accepted **40/50 (80%)** after revised judging. Five deterministic failures were ineligible for judging. An earlier judge attempt stopped at its token cap before emitting a verdict. Its cost is unknown and is excluded from the table.

## Findings and changes for the next run

| Observed issue | Change |
| --- | --- |
| `draft-workflow` took 215 seconds and returned a prose draft after reading many schemas and finding no matching table. | Teach a minimal graph and one approved preparation request with the proposed table schema when the requested draft needs a destination. |
| `check-then-watch` attempted a full agent routine for a single read-only Notion change alert. | Verify the personal connection and agent binding. Keep the watch as the proposed setup and explain the missing source when it cannot be saved. |
| `delegate-user-accepts` expected the dynamic `delegate` tool even though the shipped assistant disables dynamic specialists. It also assumed a repository absent from the workspace. | Supply the review material in the case, require `task` and validate the accepted specialist. Treat `task` as a forbidden delegation wherever the scenario disallows delegation. |
| `skill-create-durable` attempted creation without querying for the requested skill name. | Search with `list_skills` before creating or updating a named skill. |
| `diagram-approval` returned SVG source but never called `draw`. | Route a requested inline diagram through `draw` and prefer Mermaid for a simple decision flow. |
| `implicit-memory` and `durable-style-implicit` claimed persistence after an isolated write was blocked. The latter passed the revised judge despite that claim. `recall` itself was erroneously blocked. | Make the write-status requirement explicit and mark the scoped read tool as read-only. |
| `profile-role-needed` asked for links without asking which decision the person owns. The `profile-missing` case left the provisional Inbox items out of the user evidence. `context-create` claimed a saved project rule without a verified project or a successful write. | Ask about responsibility when it determines the answer, use provided Inbox items provisionally, and ask for a project link when scope cannot be verified. |
| The first judge demanded external effects for blocked writes in `private-task` and `sandbox-file`. Both passed after the grading rules distinguished an isolated attempt from a real write. | Keep the live probes for effect verification. Give judge calls bounded low reasoning and retain a technical error row when an individual case cannot be graded. |
| Both judge passes rejected `python-release`. Python.org confirms the version and release date. The judge received tool arguments and call outcomes without the fetched source text. | Retain a bounded excerpt from the official release listing in future reports. The targeted recheck of the same answer with its saved source excerpt passed ($0.00067). The aggregate judge figures above are unchanged. [Python 3.15.2 release](https://www.python.org/downloads/release/python-3152/) |

The rates above describe this baseline and each grading protocol. The candidate was not rerun after the changes. This is a trajectory and response-quality measurement. Real writes, published links and rendered artifacts are verified by the separate live probes.
