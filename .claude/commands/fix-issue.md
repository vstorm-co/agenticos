---
description: Investigate and fix an issue
---

Fix: $ARGUMENTS

1. **Understand the system, not just the symptom.** Find the code, read it, and read
   the docstring — this codebase puts the reasoning there, so the constraint you are
   about to break is usually written down a few lines above.

2. **Reproduce it.** A failing test is the ideal form. If it cannot be reproduced
   locally, say so and name what you would need.

3. **Root-cause it** along Routes → Services → Repositories. Check the layer boundary
   before the line: a route calling a repository, a service returning `None` instead of
   raising, a `commit()` in a repository.

4. **Check whether the symptom is one of the known silent failures** before assuming a
   new bug:
   - A page renders its empty state → a query failed, the UI is fine
   - Ingestion 500s on a fresh environment → the database image is not
     `pgvector/pgvector:pg16`
   - A document sits in the listing with no explanation → a format the validator accepts
     and the pipeline cannot route
   - A listing endpoint 500s after a validation change → a stored JSON row no longer
     validates
   - A background task vanished with nothing logged → bare `asyncio.create_task`
   - A tool runs unapproved → it is missing from `@register(tools=...)`
   - A Viewer with a grant is refused → a `require(...)` gate on a per-resource route

5. **Fix the cause.** Match the surrounding code. Domain exceptions in services,
   `db.flush()` in repositories, full type hints, no fallback that papers over the bug.
   Keep the diff scoped — propose follow-ups instead of taking them.

6. **Ship a regression test** that fails without the fix, in the right layer
   (`backend-tests` skill). A bug in a constraint needs `tests/integration/`; a bug in a
   gate needs `tests/api/`.

7. **Verify:** `make lint && make test-fast`, then `make test` if the platform layer
   changed. `make check` before a PR.

8. **Report** what was wrong, why it happened, and what now prevents it. If you found a
   second problem and did not fix it, say so.
