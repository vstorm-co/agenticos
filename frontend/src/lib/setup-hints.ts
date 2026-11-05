import type { Organization } from "@/types/organization";
import type { AssistantState } from "@/types/assistant";
import type { SystemAgent } from "@/lib/system-agents-api";

export type SetupHint =
  | "voiceModel"
  | "voiceKey"
  | "proactivityOff"
  | "proactivityModel"
  | "memoryModel"
  | "architectModel"
  | "mobilePush";

/** Only saved, known values count; an unread response is not missing configuration. */
export function voiceSetupHints(
  org: Partial<
    Pick<
      Organization,
      "speech_to_text_provider" | "speech_to_text_model" | "speech_to_text_secret_id"
    >
  >,
): SetupHint[] {
  if (org.speech_to_text_provider === undefined || org.speech_to_text_model === undefined)
    return [];
  if (!org.speech_to_text_provider || !org.speech_to_text_model) return ["voiceModel"];
  return org.speech_to_text_secret_id === null ? ["voiceKey"] : [];
}

export function proactivitySetupHints(
  org: Pick<Organization, "proactive_enabled" | "proactive_model_profile_id">,
): SetupHint[] {
  if (org.proactive_enabled === false) return ["proactivityOff"];
  return org.proactive_enabled && !org.proactive_model_profile_id ? ["proactivityModel"] : [];
}

export function systemAgentSetupHints(
  agent: Pick<SystemAgent, "role" | "model_profile_id">,
): SetupHint[] {
  return agent.role === "memory_maintenance" && !agent.model_profile_id ? ["memoryModel"] : [];
}

export function architectSetupHints(assistant: Pick<AssistantState, "status">): SetupHint[] {
  return assistant.status === "needs_model" ? ["architectModel"] : [];
}
