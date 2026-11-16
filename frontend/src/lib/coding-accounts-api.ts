import { apiClient } from "./api-client";

export type CodingHarness = "claude_code" | "codex";
export type ProviderUsageStatus =
  | "available"
  | "busy"
  | "rate_limited"
  | "quota_exhausted"
  | "capacity_unavailable"
  | "authentication_required"
  | "disabled"
  | "unknown";
export interface ProviderUsageWindow {
  name: string;
  used: number | null;
  limit: number | null;
  unit: string | null;
  resets_at: string | null;
}
export interface ProviderUsageSnapshot {
  status: ProviderUsageStatus;
  observed_at: string | null;
  observation_age_seconds: number | null;
  valid_until: string | null;
  source: "provider_api" | "native_runtime" | "unavailable";
  windows: ProviderUsageWindow[];
  reason_code: string | null;
}
export interface CodingAccount {
  id: string;
  harness: CodingHarness;
  label: string;
  secret_kind: "api_key" | "openai_codex";
  enabled: boolean;
  generation: string;
  is_default: boolean;
  pool_member: boolean;
  usage: ProviderUsageSnapshot;
}
export interface CodingAccountInput {
  harness: CodingHarness;
  label: string;
  api_key: string;
  enabled: boolean;
}
export interface CodingAccountChange {
  enabled: boolean;
  is_default?: true;
  pool_member?: boolean;
}

export const listCodingAccounts = () =>
  apiClient.get<{ items: CodingAccount[] }>("/coding-accounts");
export const connectCodingAccount = (data: CodingAccountInput) =>
  apiClient.post<CodingAccount>("/coding-accounts", data);
export const enableCodingAccount = (account: CodingAccount) =>
  updateCodingAccount(account, {
    enabled: !account.enabled,
  });
export const setCodingAccountDefault = (account: CodingAccount) =>
  updateCodingAccount(account, { enabled: account.enabled, is_default: true });
export const setCodingAccountPoolMember = (input: {
  account: CodingAccount;
  poolMember: boolean;
}) =>
  updateCodingAccount(input.account, {
    enabled: input.account.enabled,
    pool_member: input.poolMember,
  });
const updateCodingAccount = (account: CodingAccount, changes: CodingAccountChange) =>
  apiClient.patch<CodingAccount>(`/coding-accounts/${account.id}`, {
    generation: account.generation,
    ...changes,
  });
export const disconnectCodingAccount = (id: string) =>
  apiClient.delete<void>(`/coding-accounts/${id}`);
export const startCodingSignIn = () =>
  apiClient.post<{ authorization_url: string }>("/coding-accounts/codex/sign-in", {});
export const completeCodingSignIn = (data: {
  label: string;
  callback_url: string;
  enabled: boolean;
}) => apiClient.post<CodingAccount>("/coding-accounts/codex/complete", data);
