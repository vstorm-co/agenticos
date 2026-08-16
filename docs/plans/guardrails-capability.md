# Plan — Guardrails capability (#46)

Port `pydantic-ai-harness` guardrails into the AgenticOS capability registry. A
guardrail is an input/output/tool check that can stop, redact, or retry a run —
the platform's "value is in what it refuses" made executable.

## What the library gives us

`pydantic_ai_harness.guardrails` ships three `AbstractCapability` subclasses and a
set of ready-made detectors. All three plug into a run purely by overriding hook
methods on `pydantic_ai.capabilities.AbstractCapability` — the same base every
capability here already uses.

| Class | Hook | Edge | Verdicts it accepts |
|---|---|---|---|
| `InputGuardrail` | `wrap_model_request` (first request only) | the user prompt (`str`) | allow, block, replace |
| `OutputGuardrail` | `after_output_process` | the agent output (`object`) | allow, block, replace, retry |
| `ToolGuardrail` | `before_tool_execute` / `after_tool_execute` / `wrap_tool_execute` | tool args & results | allow, block, replace, retry, approve |

`GuardrailResult` is the shared vocabulary (`_shared.py`): a frozen dataclass with
`action ∈ {allow, block, replace, retry, approve}`, `message`, `replacement`. A
guard may return a bare `bool` (`True→allow`, `False→block`). A `guard=` may be a
single callable **or a Sequence** — a chain, where `replace` threads the
substituted value forward to every later guard (the reason chains and detectors
ship together in PR #478).

Detectors (`detectors.py`), the pieces a data-defined agent can actually select:
- `redact_secrets` — `secret_data()` over API-key/token/JWT/PEM patterns; **rewrites**, does not refuse.
- `redact_personal_data` — `personal_data()` over IBAN (mod-97), credit card (Luhn), US SSN, email.
- `secret_data(only=/extra=/placeholder=)` / `personal_data(...)` — narrow or extend.
- `blocked_keywords([...], case_sensitive=, whole_words=)` — **blocks** on the first hit.
- `for_text(detector, on_other='raise'|'allow')` — adapts a text detector to a
  non-string output (an `OutputGuardrail` may be handed a Pydantic model).

## The core tension

The harness takes **arbitrary Python callables**. An AgenticOS agent is **data** —
config, no code. A client cannot supply a callable, so the config schema must
*select and parameterise the ready-made detectors*. Everything below follows from
that: the config is a set of toggles + a delimited keyword string, and the builder
turns them into the harness detector list.

Second constraint, verified in `frontend/src/components/agents/schema-form.tsx`:
the Builder's generic form renders only **enum / number / boolean / string** —
`resolveKind` has no array branch. So a `list[str]` of keywords is not a
config field. Blocked keywords ship as a **newline/comma-delimited string** parsed
in the builder.

## Decision 1 — one capability, not three

One `guardrails` capability (`id="guardrails"`, `tools=()`, `category="utility"`),
config selecting which edges are active and which detectors run on each. Rationale:
a capability is the unit an operator switches on — "protect this agent" is one
decision, and the Builder shows one switch with a sub-form. Modelled on
`compaction/` (a non-tool, harness-wrapping capability). The three harness classes
are an implementation detail the builder assembles from config.

## Decision 2 — where a trip lands: `RunStatus.GUARDRAIL_BLOCKED`

The issue is explicit: "a guardrail trip is the platform working, not a
malfunction — model it that way." That is the exact argument `BUDGET_EXCEEDED` was
given its own status for. So: a new `RunStatus.GUARDRAIL_BLOCKED`, mirroring the
`BUDGET_EXCEEDED` mechanics end to end:

- A domain exception `GuardrailBlocked(edge, detector, message)` (a plain
  `Exception`, **not** `AppException` — same as `BudgetExceeded`), raised by the
  capability on any **block** verdict, on every edge.
- Caught in `agent_runner._run` in a new `except` clause that **does not re-raise**,
  sets `status = RunStatus.GUARDRAIL_BLOCKED`, and stores a safe `error` string
  (the refusal, never the offending content).
- New `RunStatus` member (`guardrail_blocked`, 17 chars — fits `String(24)`);
  `parse_csv` and the status filter pick it up for free.
- `_notify`: reuse the failure path or a light `notifications.guardrail_blocked`
  (optional; a distinct status already keeps operators out of the `FAILED` bucket).

**Deliberate divergence from the harness on `block`.** The harness makes an input
`block` a *graceful refusal* (`SkipModelRequest` → the refusal text becomes the
answer, run COMPLETES) and a tool `block` a `SkipToolExecution` (model continues).
For governance we want a block to be **visible**, not disguised as a completed
answer, so the capability intercepts a `block` and raises `GuardrailBlocked`
instead. `replace` (redaction) and `retry` keep harness semantics — a redactor that
scrubs a key and lets the run finish is the whole point of #478.

## Decision 3 — what NOT to port, because we already have it

An overlap pass against the existing capabilities decides two harness features out
of scope:

- **The tool-guard `approve` verdict → dropped.** AgenticOS already has
  `ApprovalGate` (`approval/_capability.py`): per-tool *human* approval that parks
  the run at `AWAITING_APPROVAL` and replays the approved arguments. That is what
  `approve` is for. Porting it would be a second, rule-driven path to the same
  `ApprovalRequired` mechanism — and the "order vs the approval gate" problem the
  issue flags exists *only* because of `approve`. Dropping it removes the collision
  entirely: the remaining tool-edge verdicts (`block`/`replace`/`retry`) are
  automated and compose cleanly with the human gate — the guardrail auto-redacts or
  refuses; the gate still asks a human for a side-effecting tool.
- **`hidden=` → dropped.** "Drop a tool from what the model sees" is already
  expressed by not binding the capability. A second mechanism is dead weight.

For completeness: pydantic-ai core ships `RaiseContentFilterError`, which reacts to
the *provider's own* safety-filter finish reason. It is unused here and orthogonal
— it does not inspect content against our rules — so it is neither a substitute for
guardrails nor part of this port.

## Decision 4 — order vs budget

Factory middleware order is outermost-first: `ReinjectSystemPrompt, budget,
ApprovalGate, *configured, gauge`. The guardrail arrives inside `*configured`, so
budget is checked before a guardrail could spend. A config-driven port spends
nothing (detectors are pure functions), so #16's metering is not yet engaged. A
future model-calling detector must wrap its spend in `record_ambient_usage` exactly
like `MeteredCompaction`; the plan reserves that seam and tests it as inert for now.

## Scope — three text edges, one branch

The detectors are **text** detectors, and the harness ships adapters for exactly the
text edges: native `str` (input prompt), `for_text` (output), `for_tool_result_text`
(tool result). Tool *arguments* are a structured `Mapping` with no ready-made text
adapter, so they are out of scope — not deferred so much as "the library does not
offer a config-driven way to do it." So the port is three edges:

- **input** — `InputGuardrail(guard=[...])` on the prompt.
- **output** — `OutputGuardrail(guard=[for_text(d, on_other='allow'), ...])`.
- **tool result** — `ToolGuardrail(result_guard=..., guard=None)` — result screening
  only; no `guard` (args), no `approve`, no `hidden`.

`on_other='allow'` on the output/result adapters is deliberate and hardcoded: a
typed output or a non-text tool result cannot be scrubbed, and *raising* there would
fail a run over content a guard could not even read. Allowing it through is the
harness's own recommended default and the honest one.

## Config schema

```python
class GuardrailsConfig(BaseModel):
    # input edge — the user prompt
    redact_secrets_in: bool = False
    redact_pii_in: bool = False
    blocked_keywords_in: str = ""     # newline/comma-delimited, parsed in the builder
    # output edge — the final answer
    redact_secrets_out: bool = False
    redact_pii_out: bool = False
    blocked_keywords_out: str = ""
    # tool-result edge — untrusted content from MCP / RAG / files
    redact_secrets_tool: bool = False
    redact_pii_tool: bool = False
    blocked_keywords_tool: str = ""
```

All flat scalars + strings — renders in the Builder's generic form. An agent that
enables the capability but leaves every field default produces empty guard chains on
every edge → the builder returns `None` ("contributes nothing to this agent", the way
`knowledge` does with no collections). That is the "pays nothing when absent" test.

## Work breakdown (one branch)

1. **Capability** — `capabilities/guardrails/{__init__.py,_capability.py,README.md}`
   (no `_toolset.py`; `tools=()`). `_capability.py` builds the harness
   `InputGuardrail` / `OutputGuardrail` / `ToolGuardrail(result_guard=...)` from
   config, and wraps each edge's `block` verdict to raise `GuardrailBlocked` instead
   of the harness's graceful-refusal control flow. Register with `tools=()`,
   `config_schema=GuardrailsConfig`, `category="utility"`. Add to `load_builtins()`.
2. **Outcome** — `RunStatus.GUARDRAIL_BLOCKED` in `db/models/agent_run.py`; a new
   `except GuardrailBlocked` clause in `agent_runner._run` that sets the status and a
   safe `error` (the refusal, never the offending content) and does not re-raise; a
   `_notify` branch (light — a distinct status already keeps it out of `FAILED`).
3. **Exception** — `GuardrailBlocked(edge, detector, message)` in the capability
   package, a plain `Exception` like `BudgetExceeded`.
4. **Tests** (100% on `app/agents/**`): each toggle builds the right detector chain;
   a `block` on each edge → `GuardrailBlocked` → `GUARDRAIL_BLOCKED`; a redaction
   rewrites and the run COMPLETES; all-default config → `None` (pays nothing); the
   runner mapping; the keyword-string parser (blank, whitespace, delimiters).
5. **Docs** — `docs/reference/capabilities.md` (docstring-generated) and
   `docs/governance.md` (guardrails beside budgets/approvals), plus the new
   `RunStatus` wherever run outcomes are described.

If a follow-up wants tool-**argument** screening or a model-calling detector, that is
a separate issue: args need a custom (non-shipped) adapter, and a model call engages
the `record_ambient_usage` metering seam this port leaves reserved and inert.

## Open risk to watch

- `String(24)` and any `ck_` check constraint on `agent_runs.status` — confirm the
  width and that no enum-restricting DB constraint needs an Alembic migration for
  the new value. `agent-spec`/`alembic-migration` skills apply if the column is
  constrained.
- The E2E/status filter surfaces (`RunStatus.parse_csv`, frontend status chips) —
  a new member may need an i18n label and a filter chip; scope-check before Phase 1
  ships so the status is not invisible in the UI.
