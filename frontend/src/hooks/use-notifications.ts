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
    patchItems(updated.read_at ?? new Date().toISOString(), (item) => item.id === id);
    queryClient.setQueryData<number>(qk.notifications.unreadCount(), (prev) =>
      Math.max(0, (prev ?? 1) - 1),
    );
  };

  const markAllRead = async () => {
    await markAllNotificationsRead();
    patchItems(new Date().toISOString(), (item) => item.read_at === null);
    queryClient.setQueryData<number>(qk.notifications.unreadCount(), 0);
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
