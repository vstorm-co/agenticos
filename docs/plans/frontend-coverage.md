# Getting to 100% coverage

Goal: 100% on both stacks, with as few exclusions as we can defend. This file is
the running ledger - what is done, what is left, and how much of it there is.

Two gates, and only one of them is in `make check`:

| | Runs | Currently |
|---|---|---|
| Backend platform layer | `make test` / `make check` | **100%**, enforced |
| Backend whole app | `make coverage-all` (informational) | **66%** - 4,538 of 14,814 statements uncovered |
| Frontend | `bun run test:coverage` - **CI only** | **76.28%** statements, 89.64% branches |

`make check` runs `test:run`, not `test:coverage`. That is why the frontend gate
sat red without anyone noticing; the thresholds are now a ratchet at the standing
number, so a change that covers less than it removes fails the build.

## Frontend

### Done this pass

Five components that had **no tests at all**, 59 tests, 71.06% → 76.28%:

| Component | Lines | Tests |
|---|---|---|
| `observability-card.tsx` | 147 | 13 |
| `environments-panel.tsx` | 88 | 14 |
| `skill-library-gallery.tsx` | 112 | 12 |
| `thinking-setting.tsx` | 64 | 11 |
| `conversation-agents.tsx` | 65 | 9 |

Plus, earlier in the session: `markdown-editor` (9), `run-summary` (8),
`agents-filter` (6), `runs/agent-filter` (4), `isAppAdmin` (5).

### Left, in the order worth doing it

**No tests at all** - the bulk of the remaining gap:

| Component | Lines | Notes |
|---|---|---|
| `embeds-panel.tsx` | 351 | Public embed keys and their rotation. Security-relevant: an embed key is a bearer credential |
| `version-history.tsx` | 292 | At 3.2%. Restore publishes a *new* version; promote moves an environment. Both are rules worth pinning |
| `channel-bots-panel.tsx` | 209 | Bot registration and token handling |

**Partial** - cheaper per point, and several are one branch short:

| File | Now | What is missing |
|---|---|---|
| `skill-files.tsx` | 36.1% | The file tree, preview kinds, the sandboxed HTML iframe |
| `add-model.tsx` | 51.2% | The key-picking branches and the inline-secret path |
| `create-skill-dialog.tsx` | 66.5% | Validation and the resource editor |
| `use-skills.ts` | 71.5% | Mutation callbacks |
| `use-agents.ts` | 74.0% | Mutation callbacks |
| `agent-map.tsx` | 80.3% | Zoom and the empty-node branches |
| `collection-picker.tsx` | 80.3% | The `pending > 0` and loading branches |
| `skill-workbench.tsx` | 80.5% | |
| `exposures-panel.tsx` | 81.2% | |
| `skill-gallery.tsx` | 86.7% | The orphan warning |
| `capability-workbench.tsx` | 88.9% | The search-empty branch |
| `agent-card.tsx` | 93.8% | |
| `use-exposures.ts` | 93.0% | |
| `capability-settings.tsx` | 95.7% | |
| `model-combobox.tsx` | 95.9% | The `contextLabel` sub-1000 branch |
| `alerts-panel.tsx` | 96.2% | The disabled-member branches |
| `model-profile-picker.tsx` | 97.7% | |
| `sharing-panel.tsx` | 98.5% | |
| `model-settings-form.tsx` | 99.0% | One line |

**Then the exclusions to argue about.** The coverage `include` is a curated list -
six hooks, three component directories and one lib file. Pages, stores, the
remaining hooks and most of `lib/` are not measured at all. Reaching a *true* 100%
means widening that list, which will drop the headline number sharply before it
climbs. Worth doing deliberately, one directory at a time, rather than in one go.

`functions` deserves its own note: it trails statements because React Query's
`onSuccess`/`onError` callbacks are one-line toasts. They are reachable - mount a
query client, fire the mutation, assert the toast - so they are not an argument for
an exclusion, only for doing the hooks as a batch.

## Backend

The platform layer is at 100% and gated. The whole app is at 66%, and the 4,538
uncovered statements are concentrated in template-inherited I/O:

| Module | Missing |
|---|---|
| `worker/tasks/rag_tasks.py` | 185 |
| `services/rag/documents.py` | 159 |
| `services/channels/router.py` | 138 |
| `services/rag/vectorstore.py` | 126 |
| `services/rag/retrieval.py` | 100 |
| `services/channels/slack.py` | 96 |
| `services/channels/telegram.py` | 87 |
| `services/channels/mattermost.py` | 82 |
| `services/rag/ingestion.py` | 81 |
| `services/rag_document.py` | 72 |
| `services/rag/connectors/google_drive.py` | 59 |
| `services/rag/sources/google_drive.py` | 40 |
| `services/rag/connectors/s3.py` | 39 |
| ...and roughly 3,300 more spread thin | |

`CLAUDE.md` currently argues against holding these to the platform bar, on the
grounds that testing an adapter's internals through mocks "buys a coverage number
rather than confidence". That argument is worth revisiting rather than deleting:
several of these are not really adapters -

- `channels/router.py` decides which agent answers a mention, **as which user**.
  That is an authorization path and it belongs in the gated set.
- `rag/retrieval.py` and `vectorstore.py` decide what an agent is allowed to read
  back. Also authorization, dressed as search.
- `rag_tasks.py` is where an upload dies silently, which this repository has
  already been bitten by.

The genuinely mock-only ones are the transport edges: `slack.py`, `telegram.py`,
`mattermost.py`, `connectors/*`, `providers/smtp.py`. Those are where an
integration test against a fake server earns more than a mocked unit test.

### Suggested order

1. Move `channels/router.py`, `rag/retrieval.py`, `rag/vectorstore.py` and
   `worker/tasks/rag_tasks.py` into the gated list, one at a time, covering each
   to 100% as it goes in. These four are ~550 statements and carry real rules.
2. `rag/documents.py`, `rag/ingestion.py`, `rag_document.py` - the pipeline. ~310.
3. The transport edges, with a fake server rather than mocks where practical.
4. Everything remaining, thin and mechanical: schemas, models, `__init__` files.

Adding a module to `[tool.coverage.run] include` also adds it to
`[[tool.ty.overrides]] include` - `tests/test_coverage_gate.py` asserts the two
lists are equal, so they move together.

## A flaky integration test, found while verifying this

`TestChattingWithAPublishedAgent::test_a_chat_turn_lands_in_run_history_as_a_web_run`
fails roughly one run in five, in isolation, with no ordering involved (there is
no `pytest-randomly` or `xdist` here). It asserts that a chat turn which ended
badly still left a row in `agent_runs`; on a bad run there is no row at all, so
`(await self._runs(db))[0]` raises `IndexError`.

The `RuntimeError` the test expects is raised and logged normally, and there is no
`run_notification_failed` in the output, so `finish()` is reached and the notifier
is not the cause. Something between `finish()` writing the row and the test's
`SELECT` seeing it is nondeterministic.

Worth knowing: every green full-suite run earlier in this session was on **Python
3.14.3**, and this reproduces on **3.12.9**, which is what `backend/.python-version`,
`requires-python`, the Dockerfile and CI all use. So it is the shipping
interpreter that flakes, and the one that was masking it was the local-only newer
one. Not attributable to this session's changes with any confidence - it needs its
own investigation, and a flaky test in CI is worse than a failing one because it
teaches people to re-run.
