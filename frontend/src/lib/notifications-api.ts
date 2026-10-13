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

export interface UnreadCount {
  count: number;
  /**
   * The scan stopped on its bound with rows still behind it, so `count` is a
   * floor rather than the truth. Kept rather than discarded: a count of zero
   * that is *approximate* still has a sweep worth offering, which is exactly
   * the case a recipient whose newest rows are all gate-hidden lands in.
   */
  approximate: boolean;
}

export async function getUnreadNotificationCount(): Promise<UnreadCount> {
  const data = await apiClient.get<Partial<UnreadCount>>(`${ROOT}/unread-count`);
  return { count: data.count ?? 0, approximate: data.approximate ?? false };
}

export async function markNotificationRead(id: string): Promise<Notification> {
  // `keepalive` for the rows that still reload the document: a `context_url`
  // written before the column held a path carries an origin, so the browser can
  // start unloading this page before an ordinary fetch flushes, and a request
  // tied to the page's lifetime does not survive that. A path navigates as a
  // sub-route and nothing unloads - but nothing migrates those older rows
  // either, so this stays until they have aged out.
  return apiClient.patch<Notification>(`${ROOT}/${id}`, undefined, { keepalive: true });
}

export interface MarkAllReadResult {
  marked: number;
  /** The sweep ran out of scan rather than out of inbox. */
  remaining: boolean;
  /** Where it stopped, to carry on from; `null` when it reached the end. */
  next_cursor: string | null;
}

export async function markAllNotificationsRead(cursor?: string): Promise<MarkAllReadResult> {
  const data = await apiClient.post<Partial<MarkAllReadResult>>(
    `${ROOT}/mark-all-read`,
    undefined,
    { params: cursor ? { cursor } : undefined },
  );
  return {
    marked: data.marked ?? 0,
    remaining: data.remaining ?? false,
    next_cursor: data.next_cursor ?? null,
  };
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
