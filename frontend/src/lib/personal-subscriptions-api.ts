import { apiClient } from "./api-client";
import type { ClaudeSubscriptionStatus } from "@/types/personal-subscriptions";

const PATH = "/personal-subscriptions/claude";

export const readClaudeSubscription = (signal: AbortSignal) =>
  apiClient.get<ClaudeSubscriptionStatus>(PATH, { signal });

export const startClaudeSubscriptionLogin = (signal: AbortSignal) =>
  apiClient.post<ClaudeSubscriptionStatus>(`${PATH}/login`, {}, { signal });

export const submitClaudeSubscriptionCode = (loginId: string, code: string, signal: AbortSignal) =>
  apiClient.post<ClaudeSubscriptionStatus>(
    `${PATH}/login/code`,
    { login_id: loginId, code },
    { signal },
  );

export const cancelClaudeSubscriptionLogin = (loginId: string, signal: AbortSignal) =>
  apiClient.post<ClaudeSubscriptionStatus>(
    `${PATH}/login/cancel`,
    { login_id: loginId },
    { signal },
  );

export const disconnectClaudeSubscription = (signal: AbortSignal) =>
  apiClient.post<ClaudeSubscriptionStatus>(`${PATH}/disconnect`, {}, { signal });

export function claudeSignInPending(status: ClaudeSubscriptionStatus | undefined): boolean {
  return (
    status?.state === "starting" ||
    status?.state === "awaiting_code" ||
    status?.state === "verifying"
  );
}

/** Only the provider's authorization page can be opened from a runtime response. */
export function claudeAuthorizationUrl(value: string | null): string | null {
  if (value === null || value.length > 8_192) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      ((url.hostname === "claude.ai" &&
        ["/oauth/authorize", "/oauth/authorize/"].includes(url.pathname)) ||
        (url.hostname === "claude.com" &&
          ["/cai/oauth/authorize", "/cai/oauth/authorize/"].includes(url.pathname))) &&
      url.username === "" &&
      url.password === "" &&
      url.port === "" &&
      url.hash === ""
      ? url.href
      : null;
  } catch {
    return null;
  }
}

/** Poll only a live sign-in, with one final check after its server-side deadline. */
export function claudeSubscriptionPollInterval(
  status: ClaudeSubscriptionStatus | undefined,
  now = Date.now(),
): number | false {
  if (!claudeSignInPending(status) || status?.expires_at == null) return false;
  return Date.parse(status.expires_at) + 5_000 > now ? 1_500 : false;
}
