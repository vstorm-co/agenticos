# `.claude/` — what lives here

Agent configuration for this repository. `CLAUDE.md` at the root is the always-loaded
brief; everything here is loaded on demand.

```
.claude/
  rules/       path-scoped conventions, matched by the `globs` in each file's frontmatter
  skills/      task-scoped guidance, selected by the `description` in SKILL.md
  commands/    slash commands (/add-endpoint, /fix-issue, /review)
  settings.json          permission allowlist, committed
  settings.local.json    per-machine, not shared
```

## The division of labour

**`docs/` is the single copy of how the system works.** It is both the published site
and the repository's engineering notes, on purpose — a second copy written for a
different reader is a copy that disagrees.

So nothing here restates `docs/`. A skill **routes** to the page and adds what a page
does not carry: which shape the work should take, which invariant is easy to break, and
which failures are silent. When a skill and a doc disagree, the doc is right and the
skill is stale.

**`rules/` is about a file you are editing.** Shapes, naming, layer boundaries. Each
file declares `globs` so it applies where it is true.

**`skills/` is about a task you are doing.** Each has a `description` written as
triggers — the phrasings a request actually arrives in, including the symptoms of the
bugs it covers.

## Skills can be more than one file

```
skills/agent-capability/
  SKILL.md                              the entry — short, decision-shaped
  references/registry-contract.md       loaded only when the detail is needed
  references/approval-and-overrides.md
```

`SKILL.md` stays small enough to be worth loading every time; the depth sits in
`references/` and is opened when the task reaches it. That is the same progressive
disclosure the product's own skills use (`docs/skills.md`) — twenty skills cost almost
nothing until one is relevant.

## The skills

| Skill | For |
|---|---|
| `agent-capability` | A tool the model can call; a capability; approval; tool renames |
| `agent-spec` | Changing `AgentSpec`, `SPEC_VERSION`, publish validation, YAML |
| `permissions-rbac` | Any authorization work. `require()` vs `resolve_access` |
| `vault-secrets` | Any credential at rest; secret kinds; leak review |
| `mcp-connections` | MCP servers, the catalog, OAuth, prefixing |
| `rag-knowledge` | Ingestion, retrieval, connectors, parsers |
| `channel-bot` | Telegram / Slack / Mattermost, mentions, webhooks |
| `background-task` | Prefect flows and the in-process handoff |
| `alembic-migration` | Schema changes and backfills |
| `backend-tests` | The four test layers and the 100% platform gate |
| `e2e-tests` | Playwright journeys and seeded fixtures |
| `frontend-feature` | Pages, data layer, stores, i18n, permission-hiding |
| `project-docs` | The mkdocs site, diagrams, icons, `--strict` |

## Keeping this honest

A skill that names a file, a flag or a command is a claim about the codebase, and a
stale claim is worse than no skill — it is confidently wrong. Two rules:

1. **Verify before writing.** Run the command, read the module, check the path.
2. **When a rename or a removal lands, grep here.** `assistant.py`,
   `CHANNEL_ENCRYPTION_KEY`, `UserRole` and `search_knowledge_base` all survived in this
   directory long after they left the code.

## Commit messages

`type(scope): summary`, Conventional Commits, enforced by a `commit-msg` hook. The
types, the scope vocabulary, what belongs in a body, and how to reference an issue
are in `CLAUDE.md` under *Git*. Only the shape is enforced — the scope list is a
suggestion, because a hook that argues about vocabulary is a hook people bypass.

`make install` wires both hook types. Plain `pre-commit install` wires only
`pre-commit`, and the subject check would silently never run.

## The docs-drift hook

`settings.json` registers a **Stop** hook running `scripts/docs_drift.py`. When a turn
ends with changes under a path some `docs/` page describes, and nothing under `docs/`
moved, it names the pages owed.

A reminder, never a gate — it always exits 0. A refactor with no behaviour change and
a test-only change legitimately owe nothing, and a check that blocked those would be
routed around within a week. The trigger map lives in the script (one place, so the
hook and the reader cannot disagree) and is summarised in `CLAUDE.md` under
*Documentation*.

Run it by hand any time: `python3 scripts/docs_drift.py`. Review or disable the hook
with `/hooks`.
