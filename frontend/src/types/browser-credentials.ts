import type { BrowserSecretMetadata } from "./secrets";

/** IDs and safe metadata only; credential values never appear in a read DTO. */
export const BROWSER_PROFILE_FIELDS = [
  "name",
  "email",
  "phone",
  "address_line1",
  "address_line2",
  "city",
  "region",
  "postal_code",
  "country",
] as const;

export type BrowserProfileField = (typeof BROWSER_PROFILE_FIELDS)[number];
export type BrowserFillField = "username" | "password" | "totp" | BrowserProfileField;
export type BrowserCredentialState =
  | "requested"
  | "preparing"
  | "awaiting_confirmation"
  | "approved"
  | "claimed"
  | "filled"
  | "submitted"
  | "refused"
  | "unknown"
  | "expired"
  | "declined";
export type BrowserCredentialReason =
  | "fill_disabled"
  | "credential_unavailable"
  | "live_browser_required"
  | "browser_ownership_lost"
  | "document_changed"
  | "destination_refused"
  | "field_refused"
  | "authority_changed"
  | "confirmation_required"
  | "confirmation_expired"
  | "confirmation_declined"
  | "output_protection_unavailable"
  | "browser_unavailable"
  | "uncertain_fill_effect"
  | "plan_already_consumed"
  | "totp_window_unavailable";

export interface BrowserCredentialPlan {
  id: string;
  operation: "fill" | "submit";
  parent_plan_id: string | null;
  run_id: string;
  call_id: string;
  tab_id: string;
  secret_id: string;
  authorization_generation: string;
  state: BrowserCredentialState;
  fields: BrowserFillField[];
  origin: string | null;
  document_id: string | null;
  expires_at: string;
  submission_expires_at: string | null;
  reason_code: BrowserCredentialReason | null;
  output_protected: boolean;
}

export interface BrowserCredentialEligible {
  id: string;
  name: string;
  kind: "browser_login" | "browser_profile";
  authorization_generation: string;
  usage_scope: "personal" | "organization";
  browser: BrowserSecretMetadata;
}

export interface BrowserCredentialPolicy {
  secret_id: string;
  authorization_generation: string;
  mode: "personal" | "shared";
  agent_ids: string[];
  member_ids: string[];
}

export interface BrowserCredentialPolicyEdit {
  generation: string;
  mode: "personal" | "shared";
  agent_ids: string[];
  member_ids: string[];
}
