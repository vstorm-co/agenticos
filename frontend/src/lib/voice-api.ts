import { apiClient } from "@/lib/api-client";
import type { RealtimeProvider, VoiceCallSurface, VoiceReadiness } from "@/types/voice";

/**
 * Whether a call to this agent would start, and why not (#54).
 *
 * `embed` asks for a widget or a hosted page, which the organization's `/chat`
 * switch does not gate.
 */
export function voiceReadiness(
  agentId: string,
  surface: VoiceCallSurface = "web",
): Promise<VoiceReadiness> {
  const query = surface === "web" ? "" : `?surface=${surface}`;
  return apiClient.get<VoiceReadiness>(`/agents/${agentId}/voice${query}`);
}

/** The realtime models a Voice section may pick from. */
export function realtimeModels(): Promise<{ items: RealtimeProvider[]; total: number }> {
  return apiClient.get<{ items: RealtimeProvider[]; total: number }>("/providers/realtime-models");
}
