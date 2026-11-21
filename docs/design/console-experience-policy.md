# Console experience and approval decisions

Maintainer Q&A, 21 November 2026. This records the agreed behavior for PR #3160;
implementation and final-head verification are tracked separately.

## Configuration ownership

- Deployment constrains availability. Organization settings choose defaults.
  A member may personalize their own experience within those constraints.
- Expose independent home-chat controls for Inbox, starter messages, greeting
  and feature hints. These control presentation, not resource authorization.
- Keep account theme and language independent from organization-scoped choices.
- Preserve existing budget, permission, connection-consent and scheduling controls.
- Keep one proactive AgenticOS personality; do not add an initiative-level setting.
- Make setup reminders subject to deployment availability, organization defaults and
  member preferences. Allow 1/3/7-day snoozes, default one day; retain manual setup
  access in settings when reminders are disabled.
- Announcements may have an explicit expiry instant. Maintenance may show a planned
  end, but an administrator must turn maintenance off.
- Use ordinary generated Architect avatars; preserve uploaded pictures and clear
  only recorded shipped marks during the upgrade.

## MCP approval

All operations retain their existing authorization and resource scope. A request
or accepted proposal authorizes ordinary work; a greeting alone does not create
resources. Tools remain annotated as writes even when their default does not
require a second approval click.

| Operation | Agreed default |
| --- | --- |
| Create/update tasks, status, dates and Kanban placement | No additional approval, including authorized shared resources |
| Add/update/upsert table records | No additional approval |
| Create a board/table/project/conversation/empty knowledge base | No additional approval |
| Any table schema change | Always ask |
| Author agent/workflow drafts, Skills/resources, Context, Datasets/cases | No additional approval |
| Answer a test agent's questions; prepare a solution review | No additional approval for the draft write |
| Execute/test an agent/workflow, eval or improvement attempt | Always ask |
| Ingest/sync documents; test a connection; run a routine now | Always ask |
| Create/change routines, watches or automatic eval suites | Always ask |
| Publish, accept an active version/improvement, promote, expose a public App link | Always ask |
| Delete records, watches, routines or drafts; settle an Inbox approval | Always ask |
| Change the cross-agent profile, model profiles or embedding endpoints | Always ask |
| Invite members, change authority, organization/deployment settings or proactivity | Always ask |
| Change the caller's console language, appearance or membership presentation | Ungated self-only presentation; no organization/deployment policy changes |

An explicit author requirement can tighten an ordinary default-free tool. The
binding's `all` policy still asks. Operations agreed as always asking cannot use
Approve all or standing unattended consent to bypass the per-call decision.

The edge-case review retains per-call approval for solution installation, agent
environments, active Skill versions and model-backed knowledge drafting.
`install_solution` creates private drafts only: it publishes, runs and indexes
nothing; its separate installation confirmation is retained deliberately.

A task or generic record write that can schedule agent work also requires approval.
Ordinary human tasks remain default-free, including authorized shared tasks. A
partial task-board upsert whose resulting execution state cannot be established
safely asks rather than assuming it is only a record edit. Existing published
workflow triggers retain the authority of their approved automation definition.

## Research informing the design

AgenticOS remains the source of truth for its actual tool contracts. External
examples support separating policy from whether an operation is a write:
[Claude permission policies](https://platform.claude.com/docs/en/managed-agents/permission-policies).
Organization policy and personal presentation also have distinct owners in
[Slack workspace policy](https://slack.com/help/articles/228020667-Manage-email-display)
and [personal sidebar preferences](https://slack.com/help/articles/212596808-Adjust-your-sidebar-preferences).
These are design references, not claims of identical product behavior.
