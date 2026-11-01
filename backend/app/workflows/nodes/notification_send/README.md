# notification.send

Notifies members of the organization in the app, by email, or both. It uses the
same notification center as budget alerts and run notices. The headline is
`subject`, and the bound `message`, if there is one, follows it.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `message` is bound |
| `out` | output | `NotificationSendOutput` | `notified_member_ids` |

Config: `recipients` (members, picked in the editor), `subject`, and `channels`
(`in_app`, `email`).

## Who can be notified

Only members, and only by id. The step cannot address an arbitrary email
address. Publishing refuses someone who is not a member. At run time each
recipient must still be an active member **and** able to see this workflow,
because a notification carries the workflow's data. A recipient who fails
either check is dropped. If nobody is left, the step fails with
`NO_PERMITTED_RECIPIENTS`.

Each person's own notification preferences still apply. `channels` can only
narrow where the notification goes. Someone who turned workflow notifications
off by email gets none.

## Acceptance is not delivery

The step completes once the notification rows are written. Email is sent later
by the delivery sweep, which retries on its own. A bounced or failed email does
not fail the workflow, and a completed step does not prove anyone read the
notification.

## Effect kind and retries

`effect_kind="write"`, `retry_guarantee="idempotent"`. The occurrence id is the
step's operation key, so a retried step writes no second notification.
