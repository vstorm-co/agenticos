/**
 * API client for the per-user notification channel preferences (#1598).
 *
 * Only the "togglable" `(event_type, channel)` pairs ever appear here -
 * `security_event`/`configuration_changed` have no preference at all, and
 * the email channel of `budget_exceeded`/`approval_requested`/
 * `usage_report`/`agent_usage_report` is still the three legacy `notify_*`
 * columns on `User`, reached through `PATCH /users/me` elsewhere on this
 * page. `docs/design/notification-center-plan.md`, Decision 4.
 */

import { apiClient } from "./api-client";

export type NotificationChannel = "in_app" | "email";

export interface NotificationPreference {
  event_type: string;
  channel: NotificationChannel;
  enabled: boolean;
}

interface NotificationPreferenceList {
  items: NotificationPreference[];
}

const ROOT = "/notifications/preferences";

export async function listNotificationPreferences(): Promise<NotificationPreference[]> {
  const data = await apiClient.get<NotificationPreferenceList>(ROOT);
  return data.items;
}

export async function updateNotificationPreference(input: {
  event_type: string;
  channel: NotificationChannel;
  enabled: boolean;
}): Promise<NotificationPreference> {
  return apiClient.patch<NotificationPreference>(ROOT, input);
}
