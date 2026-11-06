import { apiClient } from "@/lib/api-client";

export interface ToolConsent {
  id: string;
  agent_id: string;
  agent_name: string;
  tool_id: string;
  account: string | null;
  remember_scope: "conversation" | "agent";
}

export const readToolConsents = () => apiClient.get<ToolConsent[]>("/approvals/consents");
export const revokeToolConsent = (id: string) => apiClient.delete(`/approvals/${id}/consent`);
