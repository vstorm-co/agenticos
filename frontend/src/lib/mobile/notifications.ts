import { useAuthStore } from "@/stores";
import { invokeShell } from "@/lib/desktop/shell";
import { apiClient } from "@/lib/api-client";
export interface MobilePushPreferences {
  hide_previews: boolean;
  muted_conversations: string[];
}
export async function readMobilePushPreferences(): Promise<MobilePushPreferences> {
  const owner = useAuthStore.getState().user;
  const value = await apiClient.get<MobilePushPreferences & { session_id: string | null }>(
    "/push/preferences",
  );
  if (owner !== useAuthStore.getState().user)
    // i18n-exempt: internal cancellation reported to developers, never UI copy.
    throw new DOMException("The account changed while reading push settings.", "AbortError");
  if (value.session_id) await invokeShell("bind_push_session", { sessionId: value.session_id });
  return value;
}
export function saveMobilePushPreferences(
  value: MobilePushPreferences,
): Promise<MobilePushPreferences> {
  return apiClient.put("/push/preferences", value);
}
export async function setPushFocus(conversationId: string | null): Promise<void> {
  await apiClient.put("/push/focus", { conversation_id: conversationId });
}
