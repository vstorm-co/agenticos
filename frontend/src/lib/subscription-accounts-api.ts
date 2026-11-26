import { apiClient } from "./api-client";
import type { ModelProfile } from "@/types/providers";

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

export interface SubscriptionUsageWindow {
  kind: "primary" | "secondary" | "five_hour" | "seven_day" | "provider";
  label?: string | null;
  remaining_percent: number;
  duration_minutes: number | null;
  resets_at: string | null;
}

export interface SubscriptionUsage {
  status: "available" | "stale" | "unavailable";
  observed_at: string | null;
  windows: SubscriptionUsageWindow[];
}

export interface SubscriptionAccount {
  name: string;
  provider: string;
  label: string | null;
  email: string | null;
  status: string | null;
  disabled: boolean;
  unavailable: boolean;
  model_prefix?: string | null;
  usage?: SubscriptionUsage;
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

/** The vendor mark for each subscription sign-in. */
export const SUBSCRIPTION_MARK: Readonly<Record<SubscriptionProvider, string>> = {
  claude: "anthropic",
  codex: "openai",
  antigravity: "google",
  xai: "xai",
  kimi: "moonshotai",
  "kimi-ai": "moonshotai",
  devin: "devin",
  meta: "meta",
};

/** Accounts CLIProxyAPI files under another provider name than the sign-in's. */
const FILED_AS: Readonly<Partial<Record<SubscriptionProvider, readonly string[]>>> = {
  claude: ["claude", "anthropic"],
  codex: ["codex", "openai"],
  antigravity: ["antigravity", "gemini"],
};

export function subscriptionBelongsTo(
  account: SubscriptionAccount,
  provider: SubscriptionProvider,
): boolean {
  return (FILED_AS[provider] ?? [provider]).includes(account.provider.toLowerCase());
}

export function subscriptionChoice(provider: SubscriptionProvider): string {
  return `subscription:${provider}`;
}

export function subscriptionFromChoice(choice: string): SubscriptionProvider | undefined {
  return SUBSCRIPTION_PROVIDERS.find((provider) => subscriptionChoice(provider) === choice);
}

export const listSubscriptionAccountModels = (name: string) =>
  apiClient.get<string[]>(`/subscription-accounts/${encodeURIComponent(name)}/models`);

export const selectSubscriptionAccountModel = (name: string, model: string) =>
  apiClient.post<{ model: string }>(
    `/subscription-accounts/${encodeURIComponent(name)}/model-selection`,
    { model },
  );

export const readSubscriptionUsage = (name: string) =>
  apiClient.get<SubscriptionUsage>(`/subscription-accounts/${encodeURIComponent(name)}/usage`);

const HISTORIC_SUBSCRIPTION_LABELS: Readonly<Partial<Record<SubscriptionProvider, string>>> = {
  // i18n-exempt: persisted profile label prefix, matched for compatibility and never displayed.
  kimi: "Kimi Code (Moonshot)",
  // i18n-exempt: persisted profile label prefix, matched for compatibility and never displayed.
  "kimi-ai": "Kimi (kimi.com)",
};

/** Existing profile labels predate the corrected Kimi regional names. */
export function subscriptionLabelMatches(
  label: string,
  provider: SubscriptionProvider,
  displayName: string,
): boolean {
  const historic = HISTORIC_SUBSCRIPTION_LABELS[provider];
  return (
    label.startsWith(`${displayName} · `) ||
    (historic !== undefined && label.startsWith(`${historic} · `))
  );
}

/** Account routing identifies the service even when a profile has a custom label. */
export function subscriptionProviderFor(
  profile: Pick<ModelProfile, "provider" | "model" | "label"> | null | undefined,
  accounts: readonly SubscriptionAccount[],
  displayName: (provider: SubscriptionProvider) => string,
): SubscriptionProvider | undefined {
  if (profile?.provider !== "subscription_accounts") return undefined;
  const account = accounts.find(
    (entry) => entry.model_prefix && profile.model.startsWith(entry.model_prefix + "/"),
  );
  return (
    (account &&
      SUBSCRIPTION_PROVIDERS.find((provider) => subscriptionBelongsTo(account, provider))) ??
    SUBSCRIPTION_PROVIDERS.find((provider) =>
      subscriptionLabelMatches(profile.label, provider, displayName(provider)),
    )
  );
}
