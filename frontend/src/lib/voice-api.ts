import { apiClient } from "@/lib/api-client";
import type { Locale } from "@/lib/locales";
import type { VoiceSpec } from "@/types/agents";
import type { RealtimeProvider, VoiceReadiness, VoiceUsage } from "@/types/voice";

/**
 * Whether a call to this agent would start, and why not (#54).
 *
 * `embed` asks for a widget or a hosted page, which the organization's `/chat`
 * switch does not gate.
 */
export function voiceReadiness(agentId: string): Promise<VoiceReadiness> {
  return apiClient.get<VoiceReadiness>(`/agents/${agentId}/voice`);
}

/** The realtime models a Voice section may pick from. */
export function realtimeModels(): Promise<{ items: RealtimeProvider[]; total: number }> {
  return apiClient.get<{ items: RealtimeProvider[]; total: number }>("/providers/realtime-models");
}

/** Call minutes for calls started in `[start, end)`, by agent, and this month's against the limit. */
export function voiceUsage(start: string, end: string): Promise<VoiceUsage> {
  const query = new URLSearchParams({ start, end });
  return apiClient.get<VoiceUsage>(`/voice/usage?${query.toString()}`);
}

/**
 * A draft Voice section's voice saying one fixed sentence, as WAV (#54).
 *
 * The draft, not the published section: a voice is heard before anybody calls it.
 */
export async function previewVoice(
  agentId: string,
  voice: VoiceSpec,
  locale: Locale,
): Promise<Blob> {
  const response = await apiClient.raw(`/agents/${agentId}/voice/preview`, {
    method: "POST",
    body: { voice, locale },
  });
  return response.blob();
}
