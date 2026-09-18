/**
 * API client for the notification inbox itself (#1598) - the list, the
 * unread count and the two mark-read actions. The channel preferences this
 * feature also exposes live in `notification-preferences-api.ts`, a separate
 * resource with its own page.
 */

import { apiClient } from "./api-client";

export interface Notification {
  id: string;
  event_type: string;
  summary: string;
  context_url: string | null;
  /** `null` means unread - there is no separate boolean for it. */
  read_at: string | null;
  created_at: string;
}

export interface NotificationPage {
  items: Notification[];
  /** `null` means there is no next page. */
  next_cursor: string | null;
}

const ROOT = "/notifications";

export async function listNotifications(cursor?: string): Promise<NotificationPage> {
  return apiClient.get<NotificationPage>(ROOT, {
    params: cursor ? { cursor } : undefined,
  });
}

export async function getUnreadNotificationCount(): Promise<number> {
  const data = await apiClient.get<{ count: number }>(`${ROOT}/unread-count`);
  return data.count;
}

export async function markNotificationRead(id: string): Promise<Notification> {
  // `keepalive` because the caller is usually a click on a link with a real
  // destination (`context_url`): the browser can start unloading this
  // document before an ordinary fetch flushes, and a request tied to the
  // page's lifetime does not survive that.
  return apiClient.patch<Notification>(`${ROOT}/${id}`, undefined, { keepalive: true });
}

export async function markAllNotificationsRead(): Promise<number> {
  const data = await apiClient.post<{ marked: number }>(`${ROOT}/mark-all-read`);
  return data.marked;
}
