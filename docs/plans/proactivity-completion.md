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
| Review defects | Claim scope/erasure guards, effective dates, atomic numbered replies, one-time verified private-thread backfill | Wider channel attachment/approval coverage and operator guidance |
| Selected agent | Immutable routine version pins through the shared runner, API, MCP and UI | Selected-agent watches and enforced source ceilings |
| Chat management | Trusted private-chat provenance, source delivery, management cards, MCP end/budget controls | Complete responsibility flow and end-time controls in the form |
| Standing authority | Existing creator consent is preserved for immutable pins | Per-action waivers, persistent device/folder/operation grants and per-effect revocation |
| Follow-through | Existing workflow engine retained as the durability owner | Event/deadline presets, matching replies, restart/cancellation/idempotency acceptance |
| Outcomes | Existing outcome state retained | Notification inheritance/overrides, quiet findings versus requested reports and failure escalation |
| Memory | Admitted audience retained in jobs, scoped channel/routine capture, erasure serialization, no false starter-version attribution | Decision episodes and Improve evidence integration with #2172 |
| Voice | Existing realtime path retained | Twilio inbound/outbound PSTN, transfer/contact policies, limits and source-chat cards |

Completed increments are not acceptance of the whole area. No parent issue is
closed by this checklist or the continuation PR while these gaps remain.
