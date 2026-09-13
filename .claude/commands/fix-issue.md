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

4. **Use known failure modes as hypotheses, not diagnoses.** Check the evidence:
   - Empty state: inspect the query result, error handling and rendering conditions.
   - Ingestion failure in a fresh environment: check pgvector availability and logs.
   - Stalled document: check ingestion state and validator/parser routing compatibility.
   - Listing failure after validation changes: check existing stored JSON rows.
   - Missing background task: check dispatch, task ownership and exception logging.
   - Unapproved tool execution: check registration and the approval policy.
   - A Viewer with a grant is refused: check route gates and resource access resolution.

5. **Fix the cause.** Match the surrounding code. Domain exceptions in services,
   `db.flush()` in repositories, full type hints, no fallback that papers over the bug.
   Keep the diff scoped — propose follow-ups instead of taking them.

6. **Ship a regression test** that fails without the fix, in the right layer
   (`backend-tests` skill). A bug in a constraint needs `tests/integration/`; a bug in a
   gate needs `tests/api/`.

7. **Verify** with the tests covering the fix, then the applicable lint and coverage
   gates from `CLAUDE.md`. Use frontend checks for frontend defects. Run `make check`
   before a PR.

8. **Report** what was wrong, why it happened, and what now prevents it. If you found a
   second problem and did not fix it, say so.
