# Routine tool settings review

Source: PR #3434, head `13ebd9ef4a1d2d496a7d3eaf04add175e630b8e1`.
The source contains two commits based directly on the released `bb09fedf1`.
Its CI run 45670630292 failed the coverage merge because the ask-only
`RoutineAuthority.tools_off` path had no test. The backend shards, E2E and
CodeQL passed. A regression test covers that path in this integration.

The source author's second commit fixed the demonstrated review findings:
account erasure clears tool settings, provider-executed tools cannot pretend to
support a local approval gate, and a valid replacement repairs malformed stored
settings. Alembic's revision globals are consumed by Alembic; the static-analysis
unused-variable comments do not identify dead application code.

The migration retains its source identity and filename:
`backend/alembic/versions/0365_routine_tool_settings.py`. Only its parent changes
to `0370_console_role_presentation`, allowing the release train to join its
independent migration heads without renumbering an existing revision.

## Resulting behavior

The routine follows its agent by default. Its owner can require approval before
one tool, or turn it off. Off tools are hidden from the root agent and refused
again at execution; ask rules require approval before execution. Rules apply to
the stricter of the initial run snapshot and the current routine. Removing a
restriction cannot loosen a running snapshot. Delegates retain their own rules.
No routine setting releases an approval required by the agent or platform.

The existing access dialog now shows a searchable tool list grouped by capability,
account and platform area. Each row names the agent's rule and offers Follow
agent, Ask every time (where it adds a restriction), or Off. Source review remains
separate within the dialog. Saving a legacy routine explicitly switches it to
the agent's approval rules and removes its previous standing action consents;
the dialog explains this before saving. New routine defaults remain automatic
eligible tools and one shared chat.

Review also found a data-loss case in a naive frontend integration: only currently
offered tools appear in the source response, but PUT replaces the whole restriction
set. Saving an unrelated change could otherwise erase restrictions on a temporarily
unavailable MCP tool or a tool removed by publication. The response now includes
unavailable saved restrictions. The dialog preserves and shows them until the
owner explicitly removes one or resets all rules. PUT may preserve an existing
unavailable key exactly; it still refuses a new unknown key or an unsupported
change to an unavailable one. Malformed storage remains repairable.

Tool queries are scoped by session owner and organization. The mutation refuses
a changed session before dispatch and cannot repopulate another account's cache
with a late response. The service requires the routine owner's human console
session; cross-tenant, API-key, impersonation and unattended callers are refused.
