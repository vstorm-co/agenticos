"use client";

import { useEffect } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { getRoomThread } from "@/lib/room-api";
import { onRoomChange } from "@/lib/room-events";
import { qk } from "@/lib/query-keys";
import { useRoomIdentity } from "./use-room";

/** Separate authorized history for one root; a room window is never thread history. */
export function useRoomThread(conversationId: string | null, rootMessageId: string | null) {
  const { accountId, organizationId, tenant, current } = useRoomIdentity();
  const client = useQueryClient();
  const query = useInfiniteQuery({
    queryKey: qk.roomThreads.detail(accountId, tenant, conversationId, rootMessageId),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => getRoomThread(conversationId!, rootMessageId!, pageParam),
    enabled:
      conversationId !== null &&
      rootMessageId !== null &&
      accountId !== undefined &&
      tenant !== null,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((count, page) => count + page.items.length, 0);
      return last.items.length > 0 && loaded < last.total ? last.items[0]!.id : undefined;
    },
    refetchInterval: 15_000,
    refetchOnMount: "always",
    refetchOnReconnect: "always",
  });
  useEffect(
    () =>
      onRoomChange((event) => {
        if (
          current() &&
          event.conversationId === conversationId &&
          event.accountId === accountId &&
          event.organizationId === organizationId
        ) {
          void client.invalidateQueries({
            queryKey: qk.roomThreads.detail(accountId, tenant, conversationId, rootMessageId),
          });
        }
      }),
    [accountId, organizationId, tenant, current, conversationId, rootMessageId, client],
  );
  return query;
}
