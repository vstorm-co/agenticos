# Platform approvals release review — 2026-11-25

This branch integrates only the selected changes below, against release-train commit
`0c9e016732e5bb7da4fabdb612526c88aac5e656`. Their unrelated parent branches are not
included. It does not merge, release or deploy the train.

| PR | Reviewed head | Integrated behavior |
| --- | --- | --- |
| #3416 | `4c747c169a543ec59c2780fee3a7a99fa0462b12` | External platform MCP clients receive destructive-action annotations and confirmation guidance. Existing in-product approval rules remain authoritative. |
| #3441 | `854c5323b51c0f9c2f4309b975558160319b4ec5` | Improve/eval text authored outside the platform is separated into an explicitly untrusted tool-result envelope. |
| #3444 | `b782a678ade689bcfa761b67e0bf158cb474deee` | Paid operations carry quoted estimates and version pins; changed estimates are refused before paid work, and trusted platform approval cards show the quote. |
| #3448 | `caedf38f5112d8bbf1207b27980435304d0e5f7a` | Approval cards resolve readable agent, skill, dataset, attempt and version names through the run person's access checks. |
| #3442 | `b19d82fd3deae4c765adc5e52ee8d102663d7bad` | Pending: depends on the new authority flow in unselected #3402. Applying its notification alone can send a member to a forbidden view. |

## Review corrections

- Retain the existing improvement-read permission lookup: #3441's unselected parent
  #3403 changes that contract. The new improvement describer explicitly requires
  `runs:view` before reading the session.
- Persist a knowledge-draft quote in the durable job and recheck it in the worker
  before retrieval or a model call. Reject an unavailable estimate as well as a
  higher one. Jobs submitted by older clients without a quote keep their contract.
- Only server-marked, genuinely bound platform tools receive the trusted
  `platform_tool` approval context. A third-party MCP connection named `agenticos`
  cannot impersonate a platform-enforced quote merely through its tool-name prefix.
- Validate IDs and nested evaluation arguments at the describer boundary. Missing,
  malformed or inaccessible records fall back to the original approval arguments;
  descriptions are optional, decisions are not.
- Describe quotes as start-time estimate comparisons, not guaranteed provider bill
  caps. Runtime usage remains subject to the normal budget controls.

## Verification and preview

Scoped local checks include 247 PostgreSQL integration cases, 111 unit/regression
cases, five targeted durable-quote integration cases and 83 frontend cases. The
final API/coverage batch adds 58 passing cases; a separate 21-case describer batch
covers the new module completely. A final 43-case frontend batch covers the updated
quote label. Repository commit hooks add their own recorded result.
These are local checks, not a claim of successful GitHub CI for this branch.

Before/after previews use the actual `ToolApprovalDialog` component and a synthetic
parked improvement call, without model calls. The original payload displays raw
IDs; the enriched payload displays the named agent, attempt, verdict, publish
version and quoted price. After capture, the label was clarified from “Quoted price: up to”
to “Quoted estimate” to avoid implying a provider bill cap. The harness does not grant decision permissions, so its
cards show the existing permission-required message. Preview routes were removed
and their local server stopped after capture.

- Desktop: `/private/tmp/platform-approval-before-after-desktop.png`
- Mobile: `/private/tmp/platform-approval-before-after-mobile.png`
