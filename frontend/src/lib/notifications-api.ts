/**
 * API client for the notification inbox itself (#1598) - the list, the
 * unread count, the two mark-read actions and the two that clear. The channel
 * preferences this feature also exposes live in
 * `notification-preferences-api.ts`, a separate resource with its own page.
 *
 * Clearing is a `DELETE` over the wire and not one underneath it: the server
 * keeps the row and stops listing it, because that row is what a retried
 * producer deduplicates against. Nothing on this side depends on which it is -
 * a cleared row never comes back in a listing either way - but it is why
 * dismissing a budget alert does not make the next budget check write it
 * again.
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

export async function dismissNotification(id: string): Promise<void> {
  // `keepalive` for the same reason `markNotificationRead` takes it: the row
  // this clears may be one whose link the click is already following, and an
  // ordinary fetch does not survive the document starting to unload.
  await apiClient.delete<void>(`${ROOT}/${id}`, { keepalive: true });
}

export async function clearNotifications(): Promise<number> {
  const data = await apiClient.delete<{ cleared: number }>(ROOT);
  return data.cleared;
}
