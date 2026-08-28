# Design, and the decisions behind it

Six decisions shape this codebase. Each one has consequences you will meet on
your first day, so they are worth reading before you conclude something is
missing.

## 1. An agent is data, not code

There is no `@agent.tool`, no `RunContext[Deps]`, no `app/agents/assistant.py`.
Every tool reaches a model through the **capability registry**, and agent
behaviour is changed by editing a spec rather than by editing Python.

**What this buys.** A non-engineer can change what an agent says. A spec is
versioned on publish, exportable as YAML, and reviewable in a pull request in
*your* repository rather than in ours.

**What it costs.** Adding a genuinely new *kind* of thing an agent can do means
touching the registry, which is more ceremony than a decorator. That is the
trade, taken deliberately:
[Add a capability](../howto/add-capability.md) is the page that documents it.

## 2. The spec format is versioned, and only moves forward

Every published agent and every client's exported YAML carries a
`SPEC_VERSION`. A change that only works forwards breaks agents nobody touched,
so the format moves with a migration that keeps old documents loading.

Validation happens **at publish, never at run time**. A spec that would fail is
refused while somebody is looking at a form, not three weeks later in the middle
of a run somebody scheduled.

## 3. One vault, and deliberately no second mechanism

Every secret at rest goes through `app/core/vault.py`. Sealed per organization,
so a ciphertext copied out of one tenant's row cannot be decrypted for another.

This is stated as an absolute because it was not one. A second mechanism —
a deployment-wide Fernet key on RAG connector credentials — made this sentence
untrue for a single table, and it took two migrations to remove.

[Secrets and the vault →](../secrets.md)

## 4. Permissions in code, roles composed from them

There is no role column on a user and no role-based route dependency. Authority
inside an organization is a membership row plus a permission catalog.

Three rules fall out of that, and all three are enforced by tests:

- Call sites check **permissions**, never role names.
- A **grant widens** what one person may do with one row. It never narrows.
- A role gate belongs on a **collection** route only. It cannot see the grants on
  a row, so on a per-resource route it would refuse a Viewer holding an explicit
  `edit` grant before the grant was ever consulted.

[Permissions →](../permissions.md)

## 5. Refusals are the product, so refusals are what get tested

Code that only handles the happy path is not finished here. The tests that carry
the weight are the ones checking that something is **denied**: tenant isolation
even when the caller owns the row, a budget checked *before* the model request
and recorded even when the run fails, no plaintext secret in any response, log
line or audit entry, a channel mention running as the sender rather than as the
bot.

## 6. The docs are one copy, on purpose

`docs/` is both this site and the repository's own engineering notes. There is no
second, friendlier copy written for outsiders — a second copy is a copy that
disagrees, and the disagreement is found months later by somebody acting on the
stale half.

The practical consequence: **a change that alters behaviour a page describes is
not finished until that page is updated, in the same change.** A hook names the
pages owed when a change touched the code and nothing under `docs/` moved.

## Two things that were removed and stay removed

Worth knowing, because both look like omissions.

- **`UserRole`, `User.has_role()`, `RoleChecker`, `CurrentAdmin`,
  `CurrentSuperuser`** — and the `users.role` column with them. See decision 4.
- **`app/core/crypto.py` and deployment-wide Fernet keys.** See decision 3.

## The future

The near-term shape is in [the roadmap](../ROADMAP.md), and what is actually
being worked on is
[the issue map](https://github.com/vstorm-co/agenticos/issues/168) — the clusters
of open issues, which chains block which, and what has no scope yet.
