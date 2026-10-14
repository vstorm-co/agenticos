import { apiClient } from "@/lib/api-client";
import type { RealtimeProvider, VoiceReadiness } from "@/types/voice";

/** Whether a call to this agent would start, and why not (#54). */
export function voiceReadiness(agentId: string): Promise<VoiceReadiness> {
  return apiClient.get<VoiceReadiness>(`/agents/${agentId}/voice`);
}

/** The realtime models a Voice section may pick from. */
export function realtimeModels(): Promise<{ items: RealtimeProvider[]; total: number }> {
  return apiClient.get<{ items: RealtimeProvider[]; total: number }>("/providers/realtime-models");
}
