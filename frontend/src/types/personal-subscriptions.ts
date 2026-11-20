/** The native runtime owns the sign-in; these fields never carry its credentials. */
export interface ClaudeSubscriptionStatus {
  available: boolean;
  connected: boolean;
  state: "disconnected" | "starting" | "awaiting_code" | "verifying" | "connected" | "error";
  login_id: string | null;
  authorization_url: string | null;
  expires_at: string | null;
  error_code: string | null;
}

export type ClaudeSubscriptionModel = "sonnet" | "opus" | "haiku";
