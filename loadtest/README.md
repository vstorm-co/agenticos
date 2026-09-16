# The load and resilience suite

A repeatable measurement of what one AgenticOS deployment does under a stated
workload, and what it does when that workload triples. The reasoning, the
workload's proportions, the proposed thresholds and the prerequisites are in
[`docs/load-testing.md`](../docs/load-testing.md); this file is the map of the
directory.

| File | |
|---|---|
| `scenario.py` | The workload mix and the phases. The part to disagree with |
| `thresholds.py` | What counts as a pass, proposed rather than agreed |
| `stub_model.py` | A model server that is slow on purpose, and can be told to fail |
| `seed.py` | Builds the fixture through the API: agent, collection, routine |
| `driver.py` | Offers work on a schedule and records every outcome |
| `metrics.py` | Percentiles and rates, as pure functions over the samples |
| `probes.py` | CPU, memory and database connections while the run happened |
| `report.py` | The markdown a run prints |
| `run.py` | The wiring, and the preflight that refuses a useless run |
| `results/` | Measured runs, committed |

The fixture file holds no credential: the run signs in for itself, so no bearer
token is written to disk.

Nothing here is imported by the application, and nothing in `app/` may import
it. It runs on the backend's interpreter because that already has `httpx`,
`websockets`, `uvicorn` and `asyncpg` - the suite adds no dependency.

```bash
make load-stub-model     # in one terminal
make load-seed           # once, after `make dev`
make load-test           # prints the report to stdout
```
