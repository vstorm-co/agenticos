"use client";

import { useCallback, useEffect } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { qk } from "@/lib/query-keys";
import { announceRoomChange, onRoomChange } from "@/lib/room-events";
import {
  decideRoomRoutingProposal,
  getRoomLeadPolicy,
  getRoomRoutingProposal,
  listRoomRoutingProposals,
  listRoomTaskCards,
  putRoomLeadPolicy,
  ROOM_ROUTING_PAGE_SIZE,
} from "@/lib/room-routing-api";
import { useChatStore, useConversationStore } from "@/stores";
import type {
  RoomDecisionAttempt,
  RoomLeadPolicyWrite,
  RoomProposalDecision,
} from "@/types/room-routing";
import { useRoomIdentity } from "./use-room";

function useRoutingIdentity(conversationId: string | null) {
  const identity = useRoomIdentity();
  const queryClient = useQueryClient();
  const { accountId, organizationId, tenant, current } = identity;
  const invalidate = useCallback(
    () =>
      queryClient.invalidateQueries({
        queryKey: qk.roomRouting.all(accountId, tenant, conversationId),
      }),
    [accountId, tenant, conversationId, queryClient],
  );
  useEffect(
    () =>
      onRoomChange((event) => {
        if (
          current() &&
          event.accountId === accountId &&
          event.organizationId === organizationId &&
          event.conversationId === conversationId
        )
          void invalidate();
      }),
    [current, accountId, organizationId, conversationId, invalidate],
  );
  return { ...identity, invalidate };
}

/** Re-read permissions on mount and hide cached metadata after a refused read. */
export function useRoomLeadPolicy(conversationId: string | null) {
  const identity = useRoutingIdentity(conversationId);
  const query = useQuery({
    queryKey: qk.roomRouting.policy(identity.accountId, identity.tenant, conversationId),
    queryFn: ({ signal }) => getRoomLeadPolicy(conversationId!, signal),
    enabled:
      conversationId !== null && identity.accountId !== undefined && identity.tenant !== null,
    refetchOnMount: "always",
    refetchInterval: 15_000,
    retry: false,
  });
  return { ...query, data: query.isFetchedAfterMount && query.isSuccess ? query.data : undefined };
}

/** Polling reads canonical state only. It cannot accept a proposal or start work. */
export function useRoomRoutingLists(conversationId: string, threadRoot: string | null) {
  const identity = useRoutingIdentity(conversationId);
  const enabled = identity.accountId !== undefined && identity.tenant !== null;
  const proposals = useInfiniteQuery({
    queryKey: qk.roomRouting.proposals(
      identity.accountId,
      identity.tenant,
      conversationId,
      threadRoot,
    ),
    queryFn: ({ signal, pageParam }) =>
      listRoomRoutingProposals(conversationId, threadRoot, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: (last, pages) =>
      last.has_more ? pages.length * ROOM_ROUTING_PAGE_SIZE : undefined,
    enabled,
    refetchOnMount: "always",
    refetchInterval: 15_000,
    retry: false,
  });
  const tasks = useInfiniteQuery({
    queryKey: qk.roomRouting.tasks(identity.accountId, identity.tenant, conversationId, threadRoot),
    queryFn: ({ signal, pageParam }) =>
      listRoomTaskCards(conversationId, threadRoot, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: (last, pages) =>
      last.has_more ? pages.length * ROOM_ROUTING_PAGE_SIZE : undefined,
    enabled,
    refetchOnMount: "always",
    refetchInterval: 15_000,
    retry: false,
  });
  return {
    proposals,
    tasks,
    proposalItems:
      proposals.isFetchedAfterMount && proposals.isSuccess
        ? proposals.data.pages.flatMap((page) => page.items)
        : [],
    taskItems:
      tasks.isFetchedAfterMount && tasks.isSuccess
        ? tasks.data.pages.flatMap((page) => page.items)
        : [],
  };
}

/** Keep only the frozen decision token while a refused read removes private cards. */
export function useRoomDecisionAttempt(conversationId: string, proposalId: string) {
  const { accountId, organizationId, tenant, current } = useRoomIdentity();
  const chatApi = useChatStore.useApi();
  const key = JSON.stringify([accountId, organizationId, tenant, conversationId, proposalId]);
  const attempt = useChatStore((state) => state.roomDecisionAttempts[key]) ?? null;
  return {
    attempt,
    read: () => chatApi.getState().roomDecisionAttempts[key] ?? null,
    set: (value: RoomDecisionAttempt | null) => {
      if (current()) chatApi.getState().setRoomDecisionAttempt(key, value);
    },
  };
}

export function useRoomRoutingActions(conversationId: string) {
  const { accountId, organizationId, tenant, current } = useRoomIdentity();
  const conversationApi = useConversationStore.useApi();
  const queryClient = useQueryClient();
  const invalidate = useCallback(
    () =>
      queryClient.invalidateQueries({
        queryKey: qk.roomRouting.all(accountId, tenant, conversationId),
      }),
    [accountId, tenant, conversationId, queryClient],
  );
  const isCurrent = useCallback(
    () => current() && conversationApi.getState().currentConversationId === conversationId,
    [current, conversationApi, conversationId],
  );
  const changed = useCallback(() => {
    if (!isCurrent()) return;
    announceRoomChange({ conversationId, accountId, organizationId });
    void invalidate();
    void queryClient.invalidateQueries({ queryKey: qk.durableTasks.root() });
  }, [isCurrent, conversationId, accountId, organizationId, invalidate, queryClient]);
  async function scoped<T>(operation: () => Promise<T>): Promise<T | null> {
    if (!isCurrent()) return null;
    try {
      const result = await operation();
      return isCurrent() ? result : null;
    } catch (error) {
      if (isCurrent()) throw error;
      return null;
    }
  }
  return {
    isCurrent,
    changed,
    refresh: invalidate,
    readProposal: (proposalId: string) =>
      scoped(() => getRoomRoutingProposal(conversationId, proposalId)),
    savePolicy: (input: RoomLeadPolicyWrite) =>
      scoped(() => putRoomLeadPolicy(conversationId, input)),
    decide: (proposalId: string, decision: "accept" | "discard", input: RoomProposalDecision) =>
      scoped(() => decideRoomRoutingProposal(conversationId, proposalId, decision, input)),
  };
}
