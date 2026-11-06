import { apiClient } from "./api-client";

export type CodingHarness = "claude_code" | "codex";
export interface CodingAccount {
  id: string;
  harness: CodingHarness;
  label: string;
  secret_kind: "api_key" | "openai_codex";
  enabled: boolean;
  generation: string;
}
export interface CodingAccountInput {
  harness: CodingHarness;
  label: string;
  api_key: string;
  enabled: boolean;
}

export const listCodingAccounts = () =>
  apiClient.get<{ items: CodingAccount[] }>("/coding-accounts");
export const connectCodingAccount = (data: CodingAccountInput) =>
  apiClient.post<CodingAccount>("/coding-accounts", data);
export const enableCodingAccount = (account: CodingAccount) =>
  apiClient.patch<CodingAccount>(`/coding-accounts/${account.id}`, {
    generation: account.generation,
    enabled: !account.enabled,
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
