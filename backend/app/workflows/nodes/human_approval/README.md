# human.approval

Waits until a person approves or rejects what the run is about to do, then
leaves by `approved` or `rejected`. The approver sees the step's `title` and the
`details` bound to it, in the approvals queue of the Activity page or over
`GET /api/v1/workflow-approvals`.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `details` is bound |
| `approved` | output | `HumanApprovalOutput` | `decision`, `decided_by_user_id`, `decided_at`, `note` |
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
