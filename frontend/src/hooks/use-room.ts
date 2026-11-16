"use client";

import { useCallback, useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  cancelRoomRequest,
  createTeamRoom,
  listRoomRequests,
  postRoomMessage,
} from "@/lib/room-api";
import { announceRoomChange, onRoomChange } from "@/lib/room-events";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useConversationStore, useOrgStore } from "@/stores";
import { useTenantGuard, useTenantId } from "./use-organizations";
import type { RoomMessageCreate } from "@/types/room";

/** Every result belongs to both the signed-in account and the effective tenant. */
export function useRoomIdentity() {
  const accountId = useAuthStore((state) => state.user?.id);
  const organizationId = useOrgStore((state) => state.activeOrgId);
  const tenant = useTenantId();
  const sameTenant = useTenantGuard();
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const current = useCallback(
    () =>
      mounted.current &&
      useAuthStore.getState().user?.id === accountId &&
      useOrgStore.getState().activeOrgId === organizationId &&
      sameTenant(tenant),
    [accountId, organizationId, sameTenant, tenant],
  );
  return { accountId, organizationId, tenant, current };
}

export function useRoomRequests(conversationId: string | null) {
  const identity = useRoomIdentity();
  const queryClient = useQueryClient();
  const queryKey = qk.roomRequests.list(identity.accountId, identity.tenant, conversationId);
  const query = useQuery({
    queryKey,
    queryFn: () => listRoomRequests(conversationId!),
    enabled:
      conversationId !== null && identity.accountId !== undefined && identity.tenant !== null,
    // This also recovers a missed socket event and rechecks a revoked project grant.
    refetchInterval: 5_000,
  });
  const { accountId, organizationId, tenant, current } = identity;
  useEffect(
    () =>
      onRoomChange((event) => {
        if (
          current() &&
          event.conversationId === conversationId &&
          event.accountId === accountId &&
          event.organizationId === organizationId
        ) {
          void queryClient.invalidateQueries({
            queryKey: qk.roomRequests.list(accountId, tenant, conversationId),
          });
        }
      }),
    [accountId, organizationId, tenant, current, conversationId, queryClient],
  );
  return query;
}

/** Re-read through the existing transcript reconciler; never replace a live answer. */
export function useRoomSync(conversationId: string | null, reread: (id: string) => Promise<void>) {
  const { accountId, organizationId, current } = useRoomIdentity();
  useEffect(() => {
    if (conversationId === null) return;
    let debounce: ReturnType<typeof setTimeout> | undefined;
    const refresh = () => {
      if (current()) void reread(conversationId);
    };
    const unsubscribe = onRoomChange((event) => {
      if (
        event.conversationId !== conversationId ||
        event.accountId !== accountId ||
        event.organizationId !== organizationId
      )
        return;
      clearTimeout(debounce);
      debounce = setTimeout(refresh, 100);
    });
    // A room's human-only messages need recovery even when no agent run ends.
    const interval = setInterval(refresh, 15_000);
    return () => {
      unsubscribe();
      clearTimeout(debounce);
      clearInterval(interval);
    };
  }, [accountId, organizationId, current, conversationId, reread]);
}

export function useRoomActions(conversationId: string | null) {
  const { accountId, organizationId, current } = useRoomIdentity();
  const conversationApi = useConversationStore.useApi();
  const queryClient = useQueryClient();
  const stillHere = useCallback(
    () =>
      conversationId !== null &&
      current() &&
      conversationApi.getState().currentConversationId === conversationId,
    [current, conversationApi, conversationId],
  );
  const changed = useCallback(
    (selectedId: string) => {
      announceRoomChange({ conversationId: selectedId, accountId, organizationId });
      void queryClient.invalidateQueries({ queryKey: qk.conversations.all() });
      void queryClient.invalidateQueries({ queryKey: qk.projects.all() });
    },
    [accountId, organizationId, queryClient],
  );

  const post = useCallback(
    async (input: RoomMessageCreate) => {
      if (conversationId === null || !stillHere()) return null;
      try {
        const response = await postRoomMessage(conversationId, input);
        if (!stillHere()) return null;
        changed(conversationId);
        return response;
      } catch (error) {
        if (!stillHere()) return null;
        throw error;
      }
    },
    [conversationId, stillHere, changed],
  );

  const cancel = useCallback(
    async (requestId: string) => {
      if (conversationId === null || !stillHere()) return;
      try {
        await cancelRoomRequest(conversationId, requestId);
        if (stillHere()) changed(conversationId);
      } catch (error) {
        if (stillHere()) throw error;
      }
    },
    [conversationId, stillHere, changed],
  );

  return { post, cancel, isCurrent: stillHere };
}

export function useCreateTeamRoom() {
  const { accountId, organizationId, tenant, current } = useRoomIdentity();
  const queryClient = useQueryClient();
  // Creation must start after selection settles: otherwise null -> default
  // invalidates its own successful response before the caller can open the room.
  const isReady = accountId !== undefined && organizationId !== null && tenant !== null;
  const create = useCallback(
    async (projectId: string, title: string) => {
      if (!isReady || !current()) return null;
      try {
        const conversation = await createTeamRoom(projectId, title);
        if (!current()) return null;
        void queryClient.invalidateQueries({ queryKey: qk.conversations.all() });
        void queryClient.invalidateQueries({ queryKey: qk.projects.all() });
        return conversation;
      } catch (error) {
        if (!current()) return null;
        throw error;
      }
    },
    [isReady, current, queryClient],
  );
  return { create, isReady };
}
