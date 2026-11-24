"use client";

import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  followRoomThread,
  markRoomThreadRead,
  unfollowRoomThread,
  updateRoomThreadState,
  type RoomThreadLifecycleAction,
} from "@/lib/room-api";
import { announceRoomChange } from "@/lib/room-events";
import { qk } from "@/lib/query-keys";
import { useConversationStore, useOrgStore, useAuthStore } from "@/stores";
import { useRoomIdentity } from "./use-room";

/** Room-thread writes are scoped to the currently selected account and room. */
export function useRoomThreadActions(conversationId: string, rootMessageId: string) {
  const identity = useRoomIdentity();
  const client = useQueryClient();
  const conversationApi = useConversationStore.useApi();
  const [pendingWrites, setPendingWrites] = useState(0);
  const [isMarkingRead, setMarkingRead] = useState(false);
  const { accountId, organizationId, tenant, current } = identity;

  const stillHere = useCallback(
    () =>
      current() &&
      useAuthStore.getState().user?.id === accountId &&
      useOrgStore.getState().activeOrgId === organizationId &&
      conversationApi.getState().currentConversationId === conversationId,
    [accountId, conversationApi, conversationId, current, organizationId],
  );

  const run = useCallback(
    async (operation: () => Promise<void>, read = false): Promise<boolean> => {
      if (!stillHere()) return false;
      if (read) setMarkingRead(true);
      else setPendingWrites((count) => count + 1);
      try {
        await operation();
        if (!stillHere()) return false;
        void client.invalidateQueries({
          queryKey: qk.roomThreads.detail(accountId, tenant, conversationId, rootMessageId),
        });
        announceRoomChange({ conversationId, accountId, organizationId });
        return true;
      } catch (error) {
        if (!stillHere()) return false;
        throw error;
      } finally {
        if (read) setMarkingRead(false);
        else setPendingWrites((count) => Math.max(0, count - 1));
      }
    },
    [accountId, client, conversationId, organizationId, rootMessageId, stillHere, tenant],
  );

  const updateState = useCallback(
    (action: RoomThreadLifecycleAction) =>
      run(() => updateRoomThreadState(conversationId, rootMessageId, action)),
    [conversationId, rootMessageId, run],
  );
  const follow = useCallback(
    () => run(() => followRoomThread(conversationId, rootMessageId)),
    [conversationId, rootMessageId, run],
  );
  const unfollow = useCallback(
    () => run(() => unfollowRoomThread(conversationId, rootMessageId)),
    [conversationId, rootMessageId, run],
  );
  const markRead = useCallback(
    (throughMessageId: string) =>
      run(() => markRoomThreadRead(conversationId, rootMessageId, throughMessageId), true),
    [conversationId, rootMessageId, run],
  );

  return { updateState, follow, unfollow, markRead, isPending: pendingWrites > 0, isMarkingRead };
}
