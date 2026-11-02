# Proactivity, memory and channels completion

Requested 2026-11-02. Continues PR #2606 against the contracts in #2575,
#2090 and #2082. This is an implementation checklist, not a statement that
unchecked behavior ships.

## Acceptance and delivery order

- [ ] Repair SMS prompt allocation, claim erasure/sharing/authorization,
  effective-date mutation guards and existing private-channel continuity.
- [ ] Execute watches through their selected agent, with published-version
  following/pinning and bounded approved sources.
- [ ] Create and manage watches/recurring work through the same chat/UI flow;
  retain source conversation, end time and existing routine identities.
- [ ] Persist action-specific unattended authority and device-specific grants;
  recheck permissions/revocation and expose offline waiting.
- [ ] Connect workflows/tables to durable awaited-event/deadline follow-through;
  cover restart, cancellation, matching replies and duplicate effects.
- [ ] Apply shared outcomes and notification preferences/overrides to routines;
  distinguish quiet monitoring, requested reports and explicit failures.
- [ ] Extend scope-bound memory capture and decision episodes; connect evidence
  to the existing Improve flow without publishing generalized rules automatically.
- [ ] Add Twilio inbound/outbound voice using the existing realtime path,
  authorized contact policies, scheduled reports, limits and conversation cards.
- [ ] Complete channel attachments/approvals and operator migration guidance.
- [ ] Validate focused tests, local lint, migration contracts and CI on the
  resulting SHA; update documentation and translations with behavior changes.

## Boundaries

Routes delegate to services and repositories. Existing Postgres jobs/workflow
execution own durability; tables and narrative memory never become job queues.
Provider transport remains in channel adapters. Models do not grant authority.
No merge or production deployment is part of this implementation authorization.

## Dependencies and verification

PR #2172 is still open at task start. Build against its actual Improve contract
before integrating evidence; do not introduce a parallel optimizer. Desktop/mobile
and workflow prerequisite deployment is not established merely by issue closure.
Provider tests use deterministic fakes unless a dedicated test account is available.

## Implemented increments

| Area | Implemented | Still required |
|---|---|---|
| Review defects | Claim scope/erasure guards, effective dates, atomic numbered replies, one-time verified private-thread backfill; bounded inbound/outbound MMS, media-only messages, explicit file/chart delivery with expiring copies; operator upgrade/rollback guidance | Wider channel approval coverage |
| Selected agent | Selected-agent watches through the shared runner, immutable pins/environments, approved account/tool/knowledge/context ceilings, in-flight revocation and safe legacy rebinding | General action-specific authority beyond read-only watches |
| Chat management | Trusted private-chat provenance, routine/watch source delivery, live destination authorization, explicit unavailable-delivery status and management cards, shared global/agent watch forms, MCP end/budget controls and end-time form control | Complete responsibility flow, including source-chat delivery after approval resume |
| Standing authority | Immutable-pin consent and live routine/actor/run-grant checks before root, delegate and resumed tools | Per-action waivers, persistent device/folder/operation grants and bounded source authority |
| Follow-through | Existing workflow engine retained as the durability owner | Event/deadline presets, matching replies, expiry cleanup while paused or between long cadences, restart/cancellation/idempotency acceptance |
| Outcomes | Runtime/source/delivery incidents, resumed terminal callbacks, ordering/retry guards and automatic recovery; monthly budget-pause notices and automatic case recovery; shared finding/Inbox/chat settlement, explicit restore without resending, acknowledged findings excluded from briefings; live per-routine e-mail/push limits inherited from personal preferences, quiet monitoring versus requested no-change reports, retry-safe report activations | Automatic-stop escalation policy and remaining channel integration |
| Memory | Admitted audience retained in jobs, scoped channel/routine capture, erasure serialization, no false starter-version attribution | Decision episodes and Improve evidence integration with #2172 |
| Voice | Existing realtime path retained | Twilio inbound/outbound PSTN, transfer/contact policies, limits and source-chat cards |

Completed increments are not acceptance of the whole area. No parent issue is
closed by this checklist or PR #2606 while these gaps remain.
