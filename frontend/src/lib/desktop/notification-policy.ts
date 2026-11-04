import type { DesktopNotificationPreferences } from "@/stores/desktop-preferences-store";

export function notificationConversation(path: string | null): string | null {
  if (!path) return null;
  try {
    const url = new URL(path, "https://console.invalid");
    return url.pathname.endsWith("/chat") ? url.searchParams.get("id") : null;
  } catch {
    return null;
  }
}
export function shouldNotify({
  event,
  path,
  preferences,
  activeConversation,
  focused,
}: {
  event: string;
  path: string | null;
  preferences: DesktopNotificationPreferences;
  activeConversation: string | null;
  focused: boolean;
}): boolean {
  const category =
    event === "run_completed"
      ? "completed"
      : event === "run_failed"
        ? "failed"
        : event === "approval_requested"
          ? "approvals"
          : event === "background_task_paused"
            ? "questions"
            : "other";
  if (!preferences[category]) return false;
  const conversation = notificationConversation(path);
  if (conversation && preferences.muted_conversations.includes(conversation)) return false;
  return !(focused && conversation !== null && conversation === activeConversation);
}
