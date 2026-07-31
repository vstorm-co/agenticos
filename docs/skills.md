# Skills

A skill is know-how written once and attached to many agents: how refunds are
handled, what the house style is, which checks a report must pass before it goes
out.

The thing it replaces is an instructions field that grows. Twenty procedures in
one prompt means every run pays for all twenty, and the twenty-first pushes the
conversation out of the window. Skills invert that: the agent sees only names and
one-line descriptions until it decides one is relevant, then loads the body.
Twenty skills cost almost nothing; the twenty-first costs nothing either.

The other half of the point is who writes them. A skill is a row in the database,
editable in the UI, so a support lead can fix the refund policy on a Tuesday
afternoon. No deploy, no pull request, no engineer.

## The shape

```markdown
---
name: refund-policy
description: When a refund is given without asking, when it needs approval, and how to say no.
category: support
---

# Refunds

Most refund questions are decided by the order date and one exception. Check
those before escalating anything.

## Decide without asking
...
```

The frontmatter `description` is the only part the model sees for free, so it is
the field that decides whether the skill is ever loaded. Write it as *when to
reach for this*, not as a title.

A skill may carry **resources** — further files beside it, loaded on demand.
`refund-policy` ships an `exceptions.md`; the body says when to consult it. That is
the same progressive disclosure one level down: detail that only some
conversations need does not have to be in the body that every relevant
conversation loads.

`category` is one of twenty suggestions (`support`, `engineering`, `finance`,
`legal`, `security`, `marketing`, …) and drives the filter on the skills listing. It
has no effect on what the agent sees — the model chooses by `description`, never by
category.

## How an agent reads one

Through the [`skills` capability](reference/capabilities.md#skills), which
contributes three tools:

| Tool | What it does |
|---|---|
| `list_skills` | Names and one-line descriptions of everything bound to this agent |
| `load_skill` | The full body of one skill |
| `read_skill_resource` | One file beside a skill |

A spec binds skills by id in `skill_ids`, so an agent sees the ones it was given
and nothing else. Enabling the capability with no skills bound is not useful —
give the agent skills, or leave the capability off.

## Getting skills into an organization

**Write one.** Skills → New, in the UI. This is the normal path.

**Install a bundled one.** The repository ships three as worked examples:
`refund-policy`, `code-review` and `incident-report`.

```bash
uv run agenticos cmd seed-skills                    # every organization
uv run agenticos cmd seed-skills --org <org-id>     # one
uv run agenticos cmd seed-skills --dry-run          # say what would happen, do nothing
```

`e2e/seed.setup.ts` also creates one through the UI, which is what the E2E suite
asserts against.

### Installing copies

Installing a bundled skill produces an ordinary skill owned by the organization,
editable from that moment. It is a copy, not a link.

That is deliberate. The point of a skill is that a support lead can fix the refund
policy without a deploy, and a live link back to the repository's copy would take
exactly that away — the organization would be reading a file only an engineer can
change.

### Why the library is bundled and not fetched

Adding a skill to the shipped library is a deploy. The alternative — importing from
a git URL — costs outbound network from the backend, a parser pointed at somebody
else's repository, and a promise about content nobody here has read. Each folder in
`app/core/catalog/skills/` is the same small promise the
[MCP catalog](mcp.md#the-catalog) makes: somebody looked at it.

## Skills or knowledge?

They answer different questions and the difference matters when an agent gets the
wrong one.

|  | Skills | [Knowledge](file-processing.md) |
|---|---|---|
| Contains | Procedure — how we do this | Documents — what we know |
| Written by | A person, deliberately | Ingested in bulk |
| Retrieved by | The model choosing a name | Semantic search over chunks |
| Cites | Nothing; it *is* the instruction | The passage and its source |
| Scale | Tens | Thousands of documents |

"Refunds over £500 need a manager" is a skill. The signed contract that says so is
knowledge. An agent handling refunds usually wants both, and the two capabilities
compose — `skills` for the procedure, `knowledge` for the evidence.

## Access

Skills are organization-scoped resources, governed like agents and collections:
visibility plus per-row grants on top of the role. See
[Permissions](permissions.md#layer-3-visibility-and-grants).
