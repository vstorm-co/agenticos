# Web research

Exposes `web_search` over the deployment's configured search backend.

Scoped by `web:read`, so an organization that must not let agents reach the
public internet simply does not grant it - no per-agent discipline required.

**It does not make a native search approvable.** Under `method: native` the
search is Pydantic AI's `WebSearch()` and the model provider runs it on its own
side, so `ApprovalGate` - which wraps tool execution - has no call to hold. A
binding that requires approval and sets `method` to `native` is refused at
publish, from the `provider_executed` declared in `__init__.py`, rather than
given a gate that silently never fires. `web_fetch` was fixed for this first and
this capability was not, which is how a spec asking for approval searched
unapproved with an empty queue and nothing reporting it
([#857](https://github.com/vstorm-co/agenticos/issues/857)). A version published
before either refusal existed is refused again when it is assembled, because
nothing re-validates a frozen version
([#871](https://github.com/vstorm-co/agenticos/pull/871)).
