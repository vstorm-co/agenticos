# human.approval

Waits until a person approves or rejects what the run is about to do, then
leaves by `approved` or `rejected`. The approver sees the step's `title` and the
`details` and `proposal` bound to it, in the approvals queue of the Activity page or over
`GET /api/v1/workflow-approvals`.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `details` and `proposal` are bound |
| `approved` | output | `HumanApprovalOutput` | `decision`, `decided_by_user_id`, `decided_at`, `note`, `final`, `original`, `edited` |
| `rejected` | output | `HumanApprovalOutput` | the same, for a rejection or an expiry |

## One request per step run

The first dispatch writes a `workflow_approvals` row keyed by the step's
`NodeRun` and parks the step with `Waiting(reason="approval")`. The dispatcher
accepts an approval wait with no agent run behind it only while that row is
pending, so a step that asked nothing cannot park for ever. A retry or a wake
finds the same row, which is what makes the step `idempotent`, and each loop
iteration asks on its own.

## Who decides

`approvers` names members; empty, anyone holding `approvals:decide` may decide.
Named approvers get an in-app notification when the step asks. A decision wakes
the step after it commits, and `workflow-reconcile` wakes one whose wake was
lost, or whose request passed `timeout_hours` - it then expires, and the step
leaves by `rejected` with `decision: "expired"`. Cancelling the run cancels its
pending requests.

## An editable proposal

Bind text to `proposal` - a drafted reply, say - and the approver reads it next to
the request. Turn `editable` on and the queue shows it in an editor, as `text` or
`markdown` (`proposal_format`), under `proposal_label` (`Proposal` when empty); the
approver may approve a changed version. A step with nothing bound opens an empty
editor, for the case where drafting produced nothing.

The step's output then carries:

- `final`: the version the approver approved, the proposal itself when they
  changed nothing;
- `original`: the proposal as asked (`""` when nothing was bound);
- `edited`: whether `final` differs from `original`. Line endings and trailing
  spaces are not a difference.

A step that is not `editable` shows its proposal read-only and, once approved,
hands it on unchanged as `final` with `edited` false, so later steps bind `final`
whichever mode the step is in. A rejection or an expiry carries no `final`.

The decision, `final` and `edited` are read from the request's row, so the step's
output equals what the approvals queue shows.

If the workflow sends the approved `final` through `mcp.call`, set that step's
`approval` to `none`, or the person is asked twice.
