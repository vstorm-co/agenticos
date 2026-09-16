"use client";

import { useMemo } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { getErrorMessage } from "@/lib/api-error";
import {
  getUnreadNotificationCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type Notification,
  type NotificationPage,
} from "@/lib/notifications-api";
import { qk } from "@/lib/query-keys";

// A badge nobody is staring at does not need faster than a minute - the same
// interval `useBrandingNotice` picked for the same reason.
const UNREAD_COUNT_POLL_MS = 60_000;

/**
 * The bell's badge (#1598). Its own query, separate from the list below: it
 * has to stay live while the popover is closed, and the list only has to be
 * current once it is open.
 */
export function useUnreadNotificationCount(enabled = true): number {
  const { data } = useQuery({
    queryKey: qk.notifications.unreadCount(),
    queryFn: getUnreadNotificationCount,
    enabled,
    refetchInterval: UNREAD_COUNT_POLL_MS,
  });
  return data ?? 0;
}

type InboxCache = { pages: NotificationPage[]; pageParams: unknown[] };

interface UseNotificationInboxResult {
  notifications: Notification[];
  isLoading: boolean;
  error: string | null;
  hasMore: boolean;
  isLoadingMore: boolean;
  loadMore: () => void;
  refetch: () => void;
  markRead: (id: string) => Promise<void>;
  markAllRead: () => Promise<void>;
}

/**
 * The bell's paginated list (#1598, Decision 2/7).
 *
 * `enabled` gates the fetch on the popover actually being open at least
 * once - the count above it is what a closed popover keeps current. A
 * mark-read patches this cache and the count's directly, the same
 * hand-rolled-mutation shape `useNotificationPreferences` uses, rather than
 * refetching either query for one row changing.
 */
export function useNotificationInbox(enabled: boolean): UseNotificationInboxResult {
  const tErrors = useTranslations("errors");
  const tNotifications = useTranslations("notifications");
  const queryClient = useQueryClient();

  const {
    data,
    isLoading,
    error: queryError,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    refetch,
  } = useInfiniteQuery({
    queryKey: qk.notifications.inbox(),
    queryFn: ({ pageParam }: { pageParam: string | undefined }) => listNotifications(pageParam),
    enabled,
    // Toggling `enabled` back to true on reopen does not itself refetch under
    // the app's default staleTime (five minutes) - the docstring above's "only
    // has to be current once it is open" needs every open to actually ask,
    // not serve whatever page was cached the last time it was.
    staleTime: 0,
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });

  const notifications = useMemo(() => {
    const seen = new Set<string>();
    const flattened: Notification[] = [];
    for (const page of data?.pages ?? []) {
      for (const item of page.items) {
        if (!seen.has(item.id)) {
          seen.add(item.id);
          flattened.push(item);
        }
      }
    }
    return flattened;
  }, [data]);

  const error = queryError
    ? getErrorMessage(queryError, tErrors, tNotifications("failedLoad"))
    : null;

  const patchItems = (readAt: string, matches: (item: Notification) => boolean) => {
    queryClient.setQueryData<InboxCache>(qk.notifications.inbox(), (prev) =>
      prev
        ? {
            ...prev,
            pages: prev.pages.map((page) => ({
              ...page,
              items: page.items.map((item) =>
                matches(item) ? { ...item, read_at: readAt } : item,
              ),
            })),
          }
        : prev,
    );
  };

  const markRead = async (id: string) => {
    const updated = await markNotificationRead(id);
    // The count polls every minute in the background; a poll already in
    // flight when this write lands would otherwise resolve after it and
    // replace the decremented count with the pre-write one it read - the
    // same race `useNotificationPreferences.setPreference` cancels for.
    await queryClient.cancelQueries({ queryKey: qk.notifications.inbox() });
    await queryClient.cancelQueries({ queryKey: qk.notifications.unreadCount() });
    // A rapid double-click can call this twice for the same row before the
    // first call's patch below lands - `NotificationRow`'s own `unread` gate
    // reads this same cache, which has not moved yet. Read the cache fresh
    // from the client rather than the `data` this closure captured at its
    // own render: two concurrent calls share that render, so a snapshot
    // taken once would have both see the same pre-patch value regardless of
    // which one's write actually lands first. Only the transition from
    // unread to read should ever decrement the badge.
    const cached = queryClient.getQueryData<InboxCache>(qk.notifications.inbox());
    const wasUnread = cached?.pages.some((page) =>
      page.items.some((item) => item.id === id && item.read_at === null),
    );
    patchItems(updated.read_at ?? new Date().toISOString(), (item) => item.id === id);
    if (wasUnread) {
      queryClient.setQueryData<number>(qk.notifications.unreadCount(), (prev) =>
        Math.max(0, (prev ?? 1) - 1),
      );
    }
  };

  const markAllRead = async () => {
    const marked = await markAllNotificationsRead();
    await queryClient.cancelQueries({ queryKey: qk.notifications.inbox() });
    await queryClient.cancelQueries({ queryKey: qk.notifications.unreadCount() });
    patchItems(new Date().toISOString(), (item) => item.read_at === null);
    // Not a bare `0`: the write path caps how many rows one call marks
    // (`_UNREAD_CANDIDATE_CAP`), so a backlog past that cap leaves some rows
    // genuinely still unread - `marked` is what the server actually did,
    // where `0` would claim it cleared a badge it only partly worked through.
    queryClient.setQueryData<number>(qk.notifications.unreadCount(), (prev) =>
      Math.max(0, (prev ?? marked) - marked),
    );
  };

  return {
    notifications,
    isLoading,
    error,
    hasMore: hasNextPage ?? false,
    isLoadingMore: isFetchingNextPage,
    loadMore: () => void fetchNextPage(),
    refetch: () => void refetch(),
    markRead,
    markAllRead,
  };
}
