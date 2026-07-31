# The coverage gate

## What is held to 100%

The **platform layer** — everything AgenticOS adds on top of the generated template.
CI fails below 100%. The exact list is `[tool.coverage.run] include` in
`backend/pyproject.toml`: `app/agents/**`, the permission catalog, the vault, the
secret kinds, the catalogs, and the services and repositories built on them.

Template-inherited subsystems — the RAG pipeline, connectors, channel adapters,
worker tasks — are reported by `make coverage-all` but do not gate the build. Holding
code we did not design to the same bar would mean writing mock-heavy tests over its
internals, which buys a coverage number rather than confidence. When we take
ownership of one of those subsystems, it moves into the gated list.

## Adding a module to the platform layer

Two lists, and both must be edited:

1. `[tool.coverage.run] include` in `backend/pyproject.toml`
2. `[[tool.ty.overrides]] include` — the same definition of "ours", verbatim and in
   the same order

A module held to 100% coverage is held to the type checker too.
`tests/test_coverage_gate.py` keeps the two from drifting, so forgetting the second
list fails a test rather than quietly skipping type checks.

## Two ways a module drops out silently

**`include`, not `source`.** `source` accepts only packages and directories — a file
path there is silently ignored with a `module-not-imported` warning, so a whole file
can drop out of the gate without the build noticing. This config uses `include`
globs, which do accept files. Do not "fix" it back to `source`.

**`include` only reports files that were imported.** A module nothing imports is not
measured at all rather than measured at 0%. If coverage looks suspiciously green
after you added a file, check that something imports it.

Where a directory mixes our code with the generator's (`app/commands`), the
generator's files are listed in `omit` individually rather than the directory being
excluded wholesale.

## `exclude_also`

`if TYPE_CHECKING:`, `raise NotImplementedError`, `@overload`. Nothing else. Do not
add a pragma to make a branch disappear — if a branch cannot be reached, delete it;
if it can, test it.

## When the gate fails

```bash
make test-cov     # then open backend/htmlcov/index.html
```

`show_missing = true` and `skip_covered = true` are set, so the terminal report is
already just the gaps. Read them as a list of untested branches, not as a number to
push up: the usual honest fix for an unreachable branch is deleting it.
