import { apiClient } from "./api-client";

/** Every sign-in the subscription gateway offers, in the order the console lists them. */
export const SUBSCRIPTION_PROVIDERS = [
  "claude",
  "codex",
  "antigravity",
  "xai",
  "kimi",
  "kimi-ai",
  "devin",
  "meta",
] as const;
export type SubscriptionProvider = (typeof SUBSCRIPTION_PROVIDERS)[number];

export interface SubscriptionAccount {
  name: string;
  provider: string;
  label: string | null;
  email: string | null;
  status: string | null;
  disabled: boolean;
  unavailable: boolean;
}

export interface SubscriptionAccountList {
  /** False where the deployment runs no gateway. */
  enabled: boolean;
  items: SubscriptionAccount[];
}

export interface SubscriptionSignIn {
  url: string;
  state: string;
  flow: string | null;
  user_code: string | null;
  expires_in: number | null;
}

export interface SubscriptionSignInStatus {
  /** `wait`, `ok` or `error`. */
  status: string;
  error: string | null;
}

export const listSubscriptionAccounts = () =>
  apiClient.get<SubscriptionAccountList>("/subscription-accounts");
export const startSubscriptionSignIn = (provider: SubscriptionProvider) =>
  apiClient.post<SubscriptionSignIn>("/subscription-accounts/sign-ins", { provider });
export const subscriptionSignInStatus = (state: string) =>
  apiClient.get<SubscriptionSignInStatus>(
    `/subscription-accounts/sign-ins/${encodeURIComponent(state)}`,
  );
export const completeSubscriptionSignIn = (state: string, redirectUrl: string) =>
  apiClient.post<void>(`/subscription-accounts/sign-ins/${encodeURIComponent(state)}/callback`, {
    redirect_url: redirectUrl,
  });
export const cancelSubscriptionSignIn = (state: string) =>
  apiClient.delete<void>(`/subscription-accounts/sign-ins/${encodeURIComponent(state)}`);
export const disconnectSubscriptionAccount = (name: string) =>
  apiClient.delete<void>(`/subscription-accounts/${encodeURIComponent(name)}`);
