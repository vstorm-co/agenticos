import { BROWSER_IDS } from "./browser-credential-fixtures";
import { browserPlanFixture, browserSubmissionFixture } from "./browser-credential-plan-fixtures";
import type { BrowserCredentialContinuation } from "@/types/browser-credential-continuation";

export const CONTINUATION_IDS = {
  ...BROWSER_IDS,
  continuation: "99999999-9999-4999-8999-999999999999",
  continuationDocument: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  continuationCall: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  continuationTab: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
  saved: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
  other: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
};
export const continuationSourceFixture = () => browserSubmissionFixture(browserPlanFixture());
export const browserContinuationFixture = (
  overrides: Partial<BrowserCredentialContinuation> = {},
): BrowserCredentialContinuation => {
  const source = continuationSourceFixture();
  return {
    id: CONTINUATION_IDS.continuation,
    organization_id: CONTINUATION_IDS.org,
    user_id: CONTINUATION_IDS.owner,
    run_id: source.run_id,
    source_submission_id: source.id,
    source_fill_id: source.parent_plan_id!,
    source_call_id: source.call_id,
    source_tab_id: source.tab_id,
    secret_id: source.secret_id,
    authorization_generation: source.authorization_generation,
    state: "awaiting_confirmation",
    origin: source.origin,
    document_id: CONTINUATION_IDS.continuationDocument,
    expires_at: new Date(Date.now() + 60_000).toISOString(),
    keep_signed_in: null,
    saved_sign_in_id: null,
    continuation_call_id: null,
    continuation_tab_id: null,
    reason_code: null,
    output_protected: true,
    ...overrides,
  };
};
