# Routine access: one review for sources and tools

Design for #3433, implemented in PR #3434. Decided with the maintainer on
2026-11-26. It replaces three overlapping models with one: the source review
(`approved_sources` with `follow_agent` / `restricted`), standing action consent
(`action_mode`, `action_consents`) and the per-tool narrowing that #3434 first
proposed (`tool_settings`).

## Why

The console asked one question three ways. The routine form had *Tool
approvals* (`action_mode`: automatic, manual, custom). The shield on the row
opened *Action consent*, which also held the source review and its
*Follow agent* / *Reviewed snapshot* choice. The blockers said *Review access*.

Each piece had its own rules:

- **Sources and consent went stale differently.** A stale source review
  blocked the routine. A stale consent only made its tools ask. Consent was
  bound to the agent's version, so every publish dropped it, including a
  publish that only changed instructions.
- **`follow_agent` did not follow the agent.** Any expansion beyond the
  approved ceiling stopped the routine, as `restricted` did. Only the comparison
  rules differed, so every service path forked on the mode.
- **The source mode silently changed approvals.** With `action_mode = null`,
  `follow_agent` meant "the agent's approvals; consent has no effect". The
  console said approvals were configured separately.
- **The permission gate was inconsistent.** Standing consent required
  `approvals:decide` and the organization's `chat_may_waive_approvals`.
  *Run eligible tools automatically* (`action_mode = agent`) let every tool run
  as the agent allows, which is wider, and checked neither.

## The model

A routine has one **access review**, stored in `agent_triggers.approved_sources`.
It records what the creator approved: the sources (a ceiling) and a setting
for each tool.

| Field | Meaning |
|---|---|
| `mode` | `reviewed` (default) or `trust_agent` |
| sources (`mcp_sources`, `behavior`, `spec_hash`, accounts, project, …) | The ceiling: what the routine may reach |
| `approved_ceiling` | The ceiling as reviewed. The top level is the current state within it, refreshed at admission (for example after an account reconnects) |
| `tools` | Per root-agent tool: `allow`, `ask` or `off` |
| `delegates` | `allow` or `ask`: whether delegate agents' effectful tools may run without asking |
| `intent_hash` | What the routine does: prompt, destination, run-as, event filter. A change requires a new review |
| `grandfathered` | Set only by the migration, for routines that ran under `action_mode = agent`. See [Migration](#migration) |

`action_mode`, `action_consents`, `tool_settings`, the `restricted` /
`follow_agent` choice and the `/sources`, `/actions` and `/tools` endpoints
are removed. One endpoint replaces them: `GET` and `PUT
/agents/{agent_id}/triggers/{trigger_id}/access`.

A routine never releases an approval its agent, a connection or the platform
requires. `allow` is only accepted where the agent lets the tool run freely.

### Deciding one tool call

For the root agent's tools:

1. `off`: hidden from the model and refused if called.
2. An agent, connection or platform approval applies: the call asks, in both
   modes.
3. `reviewed` mode:
    - `ask`: asks.
    - A read (no effect): runs.
    - `allow` on an effectful tool: runs without asking. The approval record
      names the creator as having consented, `decided_via = "standing"`. This
      requires the creator to hold `approvals:decide` and the organization's
      `chat_may_waive_approvals` at call time. If either is missing, the call
      asks.
    - An effectful tool with no entry (new since the review): asks.
4. `trust_agent` mode: `ask` asks. Anything else follows the agent's own setting.

A delegate agent's effectful tools ask unless `delegates` is `allow`, which
has the same permission requirement as `allow`. In `trust_agent` mode
delegates follow their own settings.

### When a review goes stale (`reviewed`)

**Blocks the routine** (blocker *Review access*, no run starts):

- a source beyond the ceiling: a new account, a new MCP tool, a new
  capability, a new or changed skill or context file, a new delegate or remote
  agent;
- a capability or MCP server binding changed in anything but its approval
  settings: its configuration, tool names or descriptions, allowed tools;
- the routine's scope (run-as, environment, version pin, event source,
  delivery) or its intent (prompt) changed;
- an MCP account reconnected as a **different** account;
- a source the routine requires is unavailable: the event source, the
  platform server without *Run as me*, or a terminal credential.

**Passes and refreshes within the ceiling:**

- removed sources, MCP tools, capabilities or bindings;
- a binding's approval settings, stricter or looser: the approval gate enforces
  them on every call and a routine never releases one, so they grant nothing.
  A review saved before this rule blocks on such a change once, until saved;
- a change to the agent's instructions, model or other non-source fields;
- an MCP account reconnected as the **same** account. The connection's
  `account_email` must be known and unchanged; otherwise it counts as a
  different account;
- an optional source that is unavailable. The run goes without it.

### `trust_agent` (danger zone)

The routine uses the agent's current sources and tools without a new review.
`ask` and `off` still apply.

- **Personal resources always need review**: the creator's personal MCP
  accounts, terminal (Mirage) accounts, and the platform server acting as the
  creator. A personal MCP account or tool outside the ceiling is left out of
  the run until reviewed. A new terminal account or a newly added platform
  binding blocks the routine.
- **Expansion is reported, not blocked.** When organization sources grow
  beyond the ceiling, the next admission records the audit event
  `routine.access_expanded`, notifies the creator and moves the ceiling.
- **Allowed only** for a schedule (not an event routine, whose input comes from
  outside), by a creator holding `approvals:decide`, in an organization with
  `routines_may_trust_agent` on. The setting defaults to off and is changed by
  someone with `approvals:decide`. If any condition stops holding, the routine
  blocks until it is reviewed again.

The scope and intent rules above still apply.

### Permissions

| Choice | Requires |
|---|---|
| Reading or saving the review | The routine's creator in person: a console session, or a key they issued for `personal:consent` (as the source review allowed) |
| `allow` on an effectful tool, `delegates = allow` | A console session, `approvals:decide` and `chat_may_waive_approvals` (as standing consent did) |
| `allow` on a read, `ask`, `off` | Nothing more |
| `trust_agent` | A console session, `approvals:decide`, `routines_may_trust_agent`, a schedule routine |

A routine created through a key or by an agent therefore starts with its
effectful tools set to ask.

`approvals:decide` belongs to Owner, Admin and Operator. A Builder can create
routines, but their effectful tools ask.

### Creating a routine

Creating a routine captures the review at once, as the current default did:

- mode `reviewed`;
- tools that the creator may allow are `allow` (every read, and every
  effectful tool when the creator holds the permissions above);
- everything else is `ask`; `delegates` follows the same rule.

*Review access before enabling* still saves the routine paused and opens the
review.

## Migration

`0375_routine_access_review.py` converts every routine in place, so no
routine gains authority and none stops:

| Before | After |
|---|---|
| `restricted` or `follow_agent` | `reviewed`. A follow review keeps its `approved_ceiling`; a restricted review without `behavior` keeps comparing its `spec_hash` until it is next saved |
| `action_mode = agent`, or `null` with `follow_agent` | `grandfathered = true`, `delegates = allow`. Tools without an entry follow the agent without a permission check, as before. `tool_settings` entries are kept as `ask` / `off` |
| `per_tool` | Consents bound to the reviewed version become `allow`; `delegates = ask` |
| `manual` | No `allow` entries; `delegates = ask` |

`grandfathered` is cleared the next time the creator saves the review. From
then the permission rules apply. Reviews migrated without an `intent_hash` do
not detect prompt changes until they are saved again.

Parked runs (`awaiting_approval`, `awaiting_answer`) have their
`routine_policy` snapshots converted the same way, so they can resume.

`downgrade()` restores the columns. Reviews map back to `restricted` or
`follow_agent`, and grandfathered and trusting ones to `action_mode = agent`. Other
`allow` entries are lost, so `per_tool` routines ask again.

## Console

One dialog, *Routine access*, opened from the shield on the routine row, from
a blocker and during setup:

- **Tools** tab, opened first: one row per tool with *Run freely* / *Ask first* /
  *Off*. A lock marks tools the agent always asks before. Rows are grouped by
  capability, account and platform, with a read / changes label. A *Set all*
  menu offers *As the agent*, *Ask for everything* and *Run freely where
  allowed*. *Delegate agents* is one more row.
- **Sources** tab: the reviewed sources by kind. An unavailable source is
  marked on its row with a link to fix it.
- **One status banner** for the most important reason the review is needed.
- **Danger zone**: *Trust the agent*, with an explicit confirmation, shown only
  where it is allowed.
- **Footer**: *Finish later* / *Save and enable* during setup; *Cancel* /
  *Save changes* otherwise.

The form loses the *Tool approvals* select. The row shows a *Trusts agent*
badge. A blocker opens the tab it concerns. The governance page gains the
*Routines may trust their agent* switch.

## Out of scope

- Delegates are allowed or asked as a whole, not per tool.
- Watches keep their own source review (`WatchSources`).
