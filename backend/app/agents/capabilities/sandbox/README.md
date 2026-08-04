# sandbox — files and a shell

A workspace an agent works in: reads, writes, and on a container-backed backend a
real shell. The tools come from
[`pydantic-ai-backend`](https://github.com/vstorm-co/pydantic-ai-backend); what
lives here is which backend an agent gets, who shares it, and what it refuses.

## Why this is not `code_execution` with more features

`code_execution` is a Python evaluator with no network, no filesystem and a
restricted standard library. That restriction is what makes it safe to grant to
anything and what makes it useless for reading a report or keeping a script.

They coexist rather than one replacing the other, and the reason is not
politeness about stored specs. `code_execution` needs no infrastructure at all,
so it works on a deployment that will never run a container — and the `state`
backend here has no shell, so on the install most people have, an agent granted
both **computes with one and remembers with the other**. Neither is a subset.

Replacing `code_execution` would also have changed what a capability id *means*
for every already-published spec: after an upgrade, `code_execution` could have
meant a Docker shell for an agent nobody touched.

## What this deliberately does not do

**Choose an image, a mount, a network mode or a ceiling.** A spec names a
backend and at most a runtime *alias*. Specs are authored in a browser by anyone
holding `edit` on an agent; one that could name a container image could name one
whose entrypoint bind-mounts `/`. Everything behind the alias is the operator's,
enforced by the service's own allowlist rather than by trust.

**Ask for approval.** The library ships a permission checker with an `ask`
action; nothing here ever produces one. `ask` is an in-run `await` that dies with
the socket, while this platform's `ApprovalGate` persists a row, mails somebody,
parks the run and resumes it. So the division is: **the ruleset denies, the
platform asks.** `_permissions.py` has the detail.

**Offer background shells.** Four more tools and a process left running in a
sandbox nobody watches finish. Not offered, so not a configuration somebody
arrives at by accident.

**Open its own workspace.** Opening one reads and writes the database, and a
capability is built inside `build_agent`, which holds no session. The runner
resolves it and passes it through `resources`; see `app/services/sandbox_workspace.py`.

## The part that is a policy, not a setting

`session_scope` decides who shares files with whom. `agent` scope means any user
of the agent reads what another user wrote — a deliberate crossing of a boundary
between people in one organization. It ships without a separate grant, so the
consequence is made *visible* instead: a warning at the field, a file panel that
says whose workspace it is rather than "this conversation's files", and an audit
entry naming who set it.

`_identity.py` is where that becomes mechanical. Two things there are worth not
undoing: a user id is hashed rather than sanitised, because dropping the
characters a session id forbids maps `a.b` and `ab` onto one workspace — one
person reading another's files — and a scope with nothing to key on raises rather
than falling back to a broader one, because the fallback would be silent.
