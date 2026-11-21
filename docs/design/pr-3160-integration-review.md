# Console release-train integration review

Reviewed against base `c9ba226598091f56a231d2f2c39d506e9e2bbbe6` on 21 November 2026. The source changes below are integrated into PR #3160. Their original PRs are not merged by this operation. Each exact diff was applied before resolving conflicts with the console changes already on this branch.

| Source | Reviewed head | Resulting behavior |
| --- | --- | --- |
| #3210 | `91b06e0e8d0e6d02d7a959605980437c35fe84f7` | Workflow settings use the existing sharing controls for visibility and person/group grants. |
| #3209 | `5b8e6c5c3660c8f4eb59f5c1d7af53b9b145fee5` | Editors can discard an unpublished draft back to the latest published spec, guarded by both draft revision and published-version identity. |
| #3211 | `f6aa4df666917b0355ececb50824b8a08daf90ec` | Inbox and personal waiting counts include actionable web-chat questions; links return to the run's question in chat. |
| #3213 | `d4f0a56670ceb7b907d36ac541c4b06e16c213a8` | Explicit OpenAI-compatible and Anthropic-compatible providers use a configured endpoint and vault credential. |
| #3207 | `9f6bb3bd68947d6c9aa552df75ce83c8ca4ea612` | Builder settings and MCP account toggles preserve existing configuration and omitted defaults. |
| #3205 | `9802dbc23a05ec0bd9837da290ec76188666727d` | Attention dots explain pending eval/improvement/knowledge-gap work; attention links open Evals. |
| #3204 | `d5c3d9d38f736e86aa148406e2cfb686f902f686` | OpenRouter retries a specific HTTP 400 reasoning-block refusal once, without modifying recorded history or replaying an already-open stream. |

## Confirmed findings corrected during integration

- **#3210:** sharing invalidated the complete workflow query tree, including unrelated node catalogs and run data. Invalidate only workflow detail and list. Private-access copy now distinguishes roles reaching shared workflows from roles reaching all workflows; explicit grants remain effective.
- **#3207:** restoring an off MCP server could ignore an explicitly selected account; disabling and restoring multiple bindings could reorder them; tool-search edits before the draft base loaded could turn an omitted default into a dirty explicit setting. Preserve account intent, stable batch order and the opening draft's omitted values. Discard adopts the returned draft through the same reset path, including budget and capability baselines.
- **#3211:** a stale explicit run link could suppress a newer waiting question; archived shared conversations appeared actionable; current participants in ownerless web-channel conversations were omitted. Consume an empty explicit lookup before trying the historical pending run, exclude archived rows, and use confirmed current participant threads without bypassing project permissions.
- **#3211 persisted JSON:** unscoped run credentials and unanswered results can be SQL `NULL`, JSON `null` or omitted fields. The queue now accepts the supported empty representations while excluding scoped credentials and admitted results. Regressions create real runs through the production repository rather than forcing artificial SQL-null fixtures.
- **#3211 with #3160:** a question older than the loaded history needs a run-correlated transcript anchor. Create a dedicated local continuation carrying the authorized run/tool-call identity, reconcile it with the real history turn, and retain the same answer receipt through submission and server acknowledgement. Do not attach it to another assistant turn or restore the composer dock.
- **#3213:** custom providers were advertised in chat but the old chat model form could not supply their required endpoint. Reuse the full endpoint/key form in both chat presentations, preserving explicit model-discovery confirmation and access to saved profiles.
- **#3209 with #3160:** the shared detail-response helper must retain `can_review_shipped_update`. Compute effective edit/publish permissions once and cover shipped/non-shipped agents, missing permissions, archive state and discard responses.
- **#3214:** the workflow node's outer deadline did not reach `mcp_session`, leaving successful slow calls subject to the transport's shorter read timeout. Pass the configured timeout to transport reads and error diagnostics, keep connection establishment separately bounded, and preserve uncertain-write and cancellation semantics.

No additional confirmed blockers were found in #3204 or #3205's reviewed scope. This is a bounded review of the incoming changes and their affected callers, not a guarantee that unrelated platform behavior is defect-free.

## Verification contract

Scoped frontend tests cover sharing invalidation, builder toggles/defaults/discard, question recovery/receipts, waiting counts and custom-provider chat forms. Backend tests cover provider validation/resolution, bounded reasoning retry, draft revision/access and question visibility. PostgreSQL cases exercise archived edit shares and live versus removed channel participants. MCP timeout tests use a real local FastMCP HTTP server, including a six-second response with a ninety-second configured budget, a short deadline, uncertain writes and cancellation.

Full coverage, build and E2E gates run in GitHub Actions for the integration SHA. Consult PR #3160's checks for final evidence; successful runs for earlier commits do not validate this combined patch. UI screenshots are captured from the isolated local QA deployment; no user draft is discarded or published to obtain a comparison.
