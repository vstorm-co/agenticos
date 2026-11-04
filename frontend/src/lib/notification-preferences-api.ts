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

export const CHAT_NOTIFICATION_CHANNELS = [
  "slack",
  "telegram",
  "mattermost",
  "teams",
  "sms",
  "imessage",
  "discord",
] as const;
export type ChatNotificationChannel = (typeof CHAT_NOTIFICATION_CHANNELS)[number];
export type NotificationChannel = "in_app" | "email" | "push" | ChatNotificationChannel;

export interface NotificationDestination {
  session_id: string;
  channel: ChatNotificationChannel;
  bot_name: string;
  account_name: string;
}

export interface NotificationRoute {
  id: string;
  channel: ChatNotificationChannel;
  session_id: string;
  available: boolean;
}

export interface NotificationRoutes {
  items: NotificationRoute[];
  destinations: NotificationDestination[];
}

export function listNotificationRoutes(): Promise<NotificationRoutes> {
  return apiClient.get<NotificationRoutes>("/notifications/destinations");
}

export function replaceNotificationRoute(input: {
  channel: ChatNotificationChannel;
  session_id: string | null;
}): Promise<NotificationRoutes> {
  return apiClient.put<NotificationRoutes>("/notifications/destinations", input);
}

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
