/** Closed, value-free receipts for an explicitly approved protected cookie session. */
export const BROWSER_CONTINUATION_STATES = [
  "requested",
  "preparing",
  "awaiting_confirmation",
  "approved",
  "claimed",
  "continued",
  "refused",
  "expired",
  "declined",
  "unknown",
] as const;
export type BrowserContinuationState = (typeof BROWSER_CONTINUATION_STATES)[number];

export const BROWSER_CONTINUATION_REASONS = [
  "continuation_disabled",
  "continuation_unavailable",
  "source_not_submitted",
  "confirmation_required",
  "confirmation_expired",
  "document_changed",
  "destination_refused",
  "authority_changed",
  "browser_ownership_lost",
  "output_protection_unavailable",
  "session_state_refused",
  "session_cookie_missing",
  "browser_unavailable",
  "uncertain_continuation",
  "continuation_already_consumed",
] as const;
export type BrowserContinuationReason = (typeof BROWSER_CONTINUATION_REASONS)[number];

export interface BrowserCredentialContinuation {
  id: string;
  organization_id: string;
  user_id: string;
  run_id: string;
  source_submission_id: string;
  source_fill_id: string;
  source_call_id: string;
  source_tab_id: string;
  secret_id: string;
  authorization_generation: string;
  state: BrowserContinuationState;
  origin: string | null;
  document_id: string | null;
  expires_at: string;
  keep_signed_in: boolean | null;
  saved_sign_in_id: string | null;
  continuation_call_id: string | null;
  continuation_tab_id: string | null;
  reason_code: BrowserContinuationReason | null;
  output_protected: true;
}

export interface BrowserContinuationRequest {
  request_id: string;
}
export interface BrowserContinuationConfirmation {
  document_id: string;
  authorization_generation: string;
  approve: boolean;
  keep_signed_in: boolean;
}
