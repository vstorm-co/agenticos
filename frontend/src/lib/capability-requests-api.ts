/**
 * The two answers to a card an agent shows for a capability it lacks (#2301):
 * switch it on, or ask the agent's owner to.
 */

import { apiClient } from "./api-client";

/** Whether the agent answers with the capability now, or it waits in the draft. */
export interface CapabilityEnabled {
  published: boolean;
}

function path(agentId: string, capabilityId: string): string {
  return `/agents/${agentId}/capabilities/${encodeURIComponent(capabilityId)}`;
}

export async function enableCapability(
  agentId: string,
  capabilityId: string,
): Promise<CapabilityEnabled> {
  return apiClient.post<CapabilityEnabled>(`${path(agentId, capabilityId)}/enable`);
}

export async function askForCapability(
  agentId: string,
  capabilityId: string,
  reason: string,
): Promise<void> {
  await apiClient.post<void>(`${path(agentId, capabilityId)}/request`, { reason });
}
