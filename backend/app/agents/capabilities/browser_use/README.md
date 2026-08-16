# Browser automation (`browser_use`)

One tool, `browse_web`, that hands a self-contained natural-language goal to an
autonomous [browser-use](https://github.com/browser-use/browser-use) agent. The
sub-agent drives a real Chromium and returns a text result. Ported from the
`pydantic-ai-harness` capability of the same name (pydantic/pydantic-ai-harness#419).

## The decisions

**The library owns the browser; this repository owns the contract.** This is the
`sandbox` arrangement: `pydantic-ai-harness`'s `BrowserUse` owns the session
lifecycle, the allowlist enforcement and the result rendering. What lives here is
registration, a config schema with sane defaults, the SSRF check on a remote
endpoint, and the one tool declaration the approval policy gates.

**`browser-use` is an optional extra, absent by default.** It pins a heavier and
older dependency tree (it drags `pydantic` and others down a minor), so it is not
a base dependency and not in CI - an operator who wants the capability installs
`agenticos[browser-use]` and provides a Chromium. The capability therefore
registers, enumerates `browse_web` and builds its toolset **with the extra
missing**: the harness is reached only through `BrowserDelegateFactory`, when
`browse_web` is actually called. A bound agent whose deployment lacks the extra
fails that one tool loudly, with the install line, rather than at import.

**`side_effecting`, on the tool and the capability.** A browser follows what a
page tells it, and the page is untrusted, so `browse_web` is prompt injection
reaching a tool with side effects. The instructions say so to the model; the
`side_effecting` flag is what lets a binding put the tool behind approval.

**Two modes, one seam.** `mode='playwright'` launches a headless Chromium next to
the agent; `mode='remote'` attaches over CDP to a `cdp_url`. A self-hosted
deployment points `remote` at a hardened, isolated browser service rather than
giving the app container a browser process - the isolation agenticos#36 brought.
The modes differ only in whether the harness gets a `cdp_url` or a `headless`
flag, so `harness_kwargs` is a pure mapping tested without the extra.

**The remote endpoint is SSRF-checked.** `cdp_url` is a URL this deployment
connects to server-side, so `_build` runs it through
`app.core.sanitize.validate_webhook_url` (allowing `ws`/`wss` alongside
`http`/`https`) - the guard's first production caller (agenticos#33). A loopback,
private, reserved or metadata address is refused before the agent is assembled.

## Known limitation - the sub-agent's model is not metered yet

The browser agent makes its own model requests inside browser-use's loop, on
browser-use's own model configuration, **outside this platform's budget ledger**.
Routing them through the run's ledger (the `budget` capability's ambient-usage
recording, the shape `MeteredCompaction` uses) is the same work as the subagent
runtime and is filed as its own issue. Until it lands, an operator enabling this
capability is enabling model spend the budget guard cannot see - which is why it
ships off by default and approval-gateable.
