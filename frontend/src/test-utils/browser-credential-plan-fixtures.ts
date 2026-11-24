import { BROWSER_IDS as ids } from "./browser-credential-fixtures";
import type { BrowserCredentialEligible, BrowserCredentialPlan } from "@/types/browser-credentials";

export const browserPlanFixture = (
  overrides: Partial<BrowserCredentialPlan> = {},
): BrowserCredentialPlan => ({
  id: ids.plan,
  operation: "fill",
  parent_plan_id: null,
  run_id: ids.run,
  call_id: "browser-call",
  tab_id: "main",
  secret_id: ids.secret,
  authorization_generation: ids.generation,
  state: "awaiting_confirmation",
  fields: ["username", "password"],
  origin: "https://accounts.example",
  document_id: ids.document,
  expires_at: new Date(Date.now() + 60_000).toISOString(),
  submission_expires_at: null,
  reason_code: null,
  output_protected: false,
  ...overrides,
});
export const browserEligibilityFixture = (): BrowserCredentialEligible => ({
  id: ids.secret,
  // i18n-exempt: synthetic saved-account name supplied by an API test fixture.
  name: "Synthetic account",
  kind: "browser_login",
  authorization_generation: ids.generation,
  usage_scope: "personal",
  browser: {
    allowed_origins: ["https://accounts.example"],
    available_fields: ["username", "password"],
    has_totp: false,
  },
});
export const browserSubmissionFixture = (
  parent: BrowserCredentialPlan,
  overrides: Partial<BrowserCredentialPlan> = {},
): BrowserCredentialPlan => ({
  ...parent,
  id: ids.child,
  parent_plan_id: parent.id,
  operation: "submit",
  state: "submitted",
  submission_expires_at: null,
  output_protected: true,
  ...overrides,
});
