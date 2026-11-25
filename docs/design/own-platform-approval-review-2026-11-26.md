# Own-person platform approvals and notifications

Reviewed sources: #3402 (`6f60325124c179ac6762bdc891144d0bc7b5eb19`), #3442
(`b19d82fd3deae4c765adc5e52ee8d102663d7bad`) and #3403
(`d6120dfe75460cbbe865f45b714ca08f1228b6df`). Only their own
changes are included. The person-only release guard from #3384 and the
ownerless-resume guard from #3385 are necessary prerequisites; the live
Skill/Context policy changes from #3393 are excluded.

A Member or Builder can answer a platform call acting as themselves without
an organization-wide `approvals:decide` permission. The exception requires
an always-asking call with the trusted gate's `platform_tool` provenance,
the same run person, and a fresh personal session. An external MCP tool
name alone grants no authority. API keys, publisher fallbacks and
impersonated sessions cannot supply that answer. Existing unmarked calls
retain the restrictive person-only release rule and gain no new permission.
An approver may reject another person's call, but cannot approve or resume
it with that person's authority. Deployment changes still need application
administration authority as well.

The queue, live cards, parked calls, channel buttons and resume service use
the same decisions. A mixed batch exposes only eligible decisions to its
person and resumes after the remaining decisions are settled. Ownerless
runs resume without borrowing the approver's platform or project authority.

Approval notices now direct the run person to their conversation. Delivery
and Inbox reads recheck the pending approval, its bound platform origin and
its current run person. Stored notification metadata cannot keep a personal
decision link alive after those conditions change. Internal routing fields
are removed from mail render data.

Improve session reads, lists and by-ID reads require `runs:view` after agent
visibility resolution. Stopping a session without that permission does not
hydrate attempts, timeline, knowledge evidence or measurement noise. The typed
stop receipt contains only the session ID and status, excluding financial,
dataset, progress and error metadata; the console clears its cached details. The MCP
adapter relies on the service's guard rather than a second permissions fetch.

Verification records belong to the source commit and combined release CI.
Local checks cover real PostgreSQL cross-person and cross-organization
refusals, API keys and publisher fallbacks, external and legacy tool names,
channel continuations, notification delivery, and Improve service guards.
No model work, production data mutation, publication or deployment is part
of this review.
