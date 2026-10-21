/**
 * API client for the remote A2A agents an organization's agents may delegate to.
 *
 * Registering one reads its agent card on the server, through the deployment's
 * address checks, so a refusal names what was wrong with the address or the card.
 */

import { apiClient } from "./api-client";
import type {
  ExternalAgent,
  ExternalAgentCreate,
  ExternalAgentList,
} from "@/types/external-agents";

const BASE = "/external-agents";

export async function listExternalAgents(): Promise<ExternalAgent[]> {
  return (await apiClient.get<ExternalAgentList>(BASE)).items;
}

export async function registerExternalAgent(input: ExternalAgentCreate): Promise<ExternalAgent> {
  return apiClient.post<ExternalAgent>(BASE, input);
}

/** Reads the agent's card again, for a name, description or skills it changed. */
export async function refreshExternalAgent(id: string): Promise<ExternalAgent> {
  return apiClient.post<ExternalAgent>(`${BASE}/${id}/refresh`, {});
}

export async function deleteExternalAgent(id: string): Promise<void> {
  await apiClient.delete<void>(`${BASE}/${id}`);
}
