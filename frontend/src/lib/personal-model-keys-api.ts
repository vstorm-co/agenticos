import { apiClient } from "./api-client";

export interface PersonalModelKey {
  id: string;
  provider: string;
  endpoint: string;
}
export interface PersonalModelDestination {
  profile_id: string;
  provider: string;
  endpoint: string | null;
  model: string;
}
export interface PersonalModelKeyCreate {
  agentId: string;
  api_key: string;
  expected_destination: PersonalModelDestination;
}
export interface AgentModelConnection {
  personal: boolean;
  connected: boolean;
  profile_id: string | null;
  provider: string | null;
  endpoint: string | null;
  model: string | null;
}
export const listPersonalModelKeys = () =>
  apiClient.get<{ items: PersonalModelKey[] }>("/personal-model-keys");
export const agentModelConnection = (agentId: string) =>
  apiClient.get<AgentModelConnection>(`/personal-model-keys/agents/${agentId}`);
export const savePersonalModelKey = (data: PersonalModelKeyCreate) =>
  apiClient.put<AgentModelConnection>(`/personal-model-keys/agents/${data.agentId}`, {
    api_key: data.api_key,
    expected_destination: data.expected_destination,
  });
export const deletePersonalModelKey = (keyId: string) =>
  apiClient.delete<void>(`/personal-model-keys/${keyId}`);

export interface CopilotSignInChallenge {
  handle: string;
  user_code: string;
  verification_uri: "https://github.com/login/device";
  expires_at: string;
  poll_after_seconds: number;
}
export interface CopilotSignInResult {
  status: "pending" | "connected";
  poll_after_seconds: number;
}
export const startCopilotSignIn = (agentId: string, destination: PersonalModelDestination) =>
  apiClient.post<CopilotSignInChallenge>(`/personal-model-keys/agents/${agentId}/copilot/sign-in`, {
    expected_destination: destination,
  });
export const pollCopilotSignIn = (agentId: string, handle: string) =>
  apiClient.post<CopilotSignInResult>(`/personal-model-keys/agents/${agentId}/copilot/poll`, {
    handle,
  });
