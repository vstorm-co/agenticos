# Contributing to AgenticOS

Thanks for looking. This document is short on ceremony and specific about the
things that actually get pull requests rejected.

## The bar

Code lands when a maintainer would merge it without changes. Concretely:

- **Fully typed.** No `Any`, no `# type: ignore`, no `except:` that makes an
  error disappear. Model with precise types rather than loose dicts.
- **Errors are loud.** Fail with a clear message; never swallow an exception or
  paper over a bug with a fallback. A silent wrong answer is worse than a crash.
- **No dead weight.** No speculative abstractions, unused parameters,
  commented-out code, or "just in case" branches.
- **Comments explain *why*.** What the code does is visible; why it does it that
  way is not, and that is the thing a reader six months from now needs.
- **Match the surrounding code.** Its idioms win over personal preference.

## Getting set up

```bash
make dev            # postgres, redis, api, worker, frontend
make seed           # an organization, an owner, a default model profile
```

The backend needs a `VAULT_MASTER_KEY`. Without one it falls back to
`SECRET_KEY`, which is fine locally and refused in production.

## Running the tests

See [`CLAUDE.md`](CLAUDE.md#testing) for the full picture. The short version:

```bash
make test               # backend, with the coverage gate
make test-frontend      # vitest unit + integration, no coverage
make test-frontend-cov  # the same, plus the gate CI applies
make test-e2e           # playwright
make check              # every CI job except e2e — run this before a pull request
```

**`make test-frontend` measures no coverage, and the frontend's only gate is a
coverage threshold.** It is the loop; `make check` is the answer.

**The platform layer is held at 100% coverage** and CI enforces it. That means
`app/agents/`, the permission catalog, the vault, and the services built on top.
Template-inherited subsystems (the RAG pipeline, connectors, channel adapters)
are reported but do not gate the build — holding code we did not design to the
same bar would mean mock-heavy tests that buy a number rather than confidence.

If you add a file to the platform layer, it needs tests that would fail if the
behaviour changed. A test that only exercises the happy path does not count.

## Architecture, in one paragraph

An agent is **data**, not code. `AgentSpec` is the contract: the Builder edits
it, the database versions it, `app/agents/factory.py` instantiates it, and a
client can commit it to their own git repository as YAML. Everything an agent is
assembled from is a **capability** — knowledge search, web research, a budget
guard, a set of skills — declared in code with metadata and composed by
configuration. Configuration can only ever reach what code registered.

Two rules follow, and most review comments come back to them:

**Ids are permanent.** A capability id appears in stored specs and in clients'
repositories. Rename the Python class freely; changing the id is a breaking
change.

**Validate at publish, not at run time.** A broken agent should be refused while
someone is looking at a form, not at 3am in a customer conversation.

## Adding a capability

One folder under `app/agents/capabilities/`, mirroring the shape of the others:

```
app/agents/capabilities/your_thing/
    __init__.py        # registration + public exports
    _capability.py     # the AbstractCapability subclass
    _toolset.py        # its tools, if it has any
    README.md          # the decisions behind it, not a description of the code
```

Register it in `_registry.py`'s `load_builtins()` or it does not exist as far as
the Builder is concerned — that coupling is deliberate.

If the capability can act on the outside world, mark it `side_effecting=True`.
That makes human approval the default, and forgetting the flag is how an agent
ends up sending email unattended.

## Pull requests

- One concern per PR. A refactor and a feature in one diff get reviewed as
  neither.
- Bugs ship with a regression test that fails without the fix.
- Say what you decided and why in the description. The code shows the what.

## Security

Do not open a public issue for a vulnerability. See [`SECURITY.md`](SECURITY.md).

## License

By contributing you agree that your work is licensed under the Apache License
2.0, the same terms as the rest of this repository. There is no CLA.
