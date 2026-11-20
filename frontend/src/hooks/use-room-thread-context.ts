"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { announceRoomChange, onRoomChange } from "@/lib/room-events";
import { qk } from "@/lib/query-keys";
import {
  createRoomThreadFromRange,
  getRoomThreadContextCandidates,
  getRoomThreadContextSourceConversation,
  getRoomThreadContextSourcePage,
  moveRoomThreadContext,
  returnRoomThreadContext,
  searchRoomThreadContextConversations,
  updateRoomThreadContext,
} from "@/lib/room-thread-context-api";
import type { Conversation } from "@/types/conversation";
import type {
  RoomThreadContextActionRead,
  RoomThreadContextCandidateMessage,
  RoomThreadContextMutationInput,
  RoomThreadContextRangeInput,
  RoomThreadContextSearchCursor,
  RoomThreadContextUpdateInput,
} from "@/types/room-thread-context";
import { useAuthStore, useConversationStore, useOrgStore } from "@/stores";
import { useRoomIdentity } from "./use-room";

export function useRoomThreadContextConversationSearch(term: string) {
  const identity = useRoomIdentity();
  const normalized = term.trim();
  const query = useInfiniteQuery({
    queryKey: qk.roomThreadContext.conversations(
      identity.accountId,
      identity.organizationId,
      identity.tenant,
      normalized,
    ),
    initialPageParam: {
      ownedSkip: 0,
      sharedSkip: 0,
      roomsSkip: 0,
    } as RoomThreadContextSearchCursor,
    queryFn: async ({ pageParam }) => {
      if (!identity.current()) throw new Error("ROOM_THREAD_CONTEXT_SCOPE_CHANGED");
      const result = await searchRoomThreadContextConversations(normalized, pageParam);
      if (!identity.current()) throw new Error("ROOM_THREAD_CONTEXT_SCOPE_CHANGED");
      return result;
    },
    getNextPageParam: (last) => last.nextCursor ?? undefined,
    enabled: normalized !== "" && identity.accountId !== undefined && identity.tenant !== null,
    staleTime: 10_000,
  });
  const items = useMemo(() => {
    const unique = new Map<string, Conversation>();
    for (const page of query.data?.pages ?? []) {
      for (const item of page.items) unique.set(item.id, unique.get(item.id) ?? item);
    }
    return [...unique.values()].sort(
      (left, right) =>
        Date.parse(right.updated_at ?? right.created_at) -
        Date.parse(left.updated_at ?? left.created_at),
    );
  }, [query.data?.pages]);
  return { ...query, items };
}

export function useRoomThreadContextSourceConversation(
  conversationId: string | null,
  enabled = true,
) {
  const identity = useRoomIdentity();
  return useQuery({
    queryKey: qk.roomThreadContext.sourceConversation(
      identity.accountId,
      identity.organizationId,
      identity.tenant,
      conversationId,
    ),
    queryFn: async () => {
      if (!identity.current() || conversationId === null)
        throw new Error("ROOM_THREAD_CONTEXT_SCOPE_CHANGED");
      const result = await getRoomThreadContextSourceConversation(conversationId);
      if (!identity.current()) throw new Error("ROOM_THREAD_CONTEXT_SCOPE_CHANGED");
      return result;
    },
    enabled:
      enabled &&
      conversationId !== null &&
      identity.accountId !== undefined &&
      identity.tenant !== null,
  });
}

function mergeSourceMessages(
  pages: readonly { items: readonly RoomThreadContextCandidateMessage[] }[],
): RoomThreadContextCandidateMessage[] {
  const unique = new Map<string, RoomThreadContextCandidateMessage>();
  for (const page of [...pages].toReversed()) {
    for (const item of page.items) unique.set(item.id, item);
  }
  return [...unique.values()];
}

/** Read an independently selected source without changing the open destination chat. */
export function useRoomThreadContextSource(sourceConversationId: string | null, enabled = true) {
  const identity = useRoomIdentity();
  const { accountId, organizationId, tenant, current: isCurrentScope } = identity;
  const client = useQueryClient();
  const query = useInfiniteQuery({
    queryKey: qk.roomThreadContext.source(
      identity.accountId,
      identity.organizationId,
      identity.tenant,
      sourceConversationId,
    ),
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      if (!identity.current() || sourceConversationId === null)
        throw new Error("ROOM_THREAD_CONTEXT_SCOPE_CHANGED");
      const page = await getRoomThreadContextSourcePage(sourceConversationId, pageParam);
      if (!identity.current()) throw new Error("ROOM_THREAD_CONTEXT_SCOPE_CHANGED");
      return page;
    },
    enabled:
      enabled &&
      sourceConversationId !== null &&
      identity.accountId !== undefined &&
      identity.tenant !== null,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((count, page) => count + page.rawCount, 0);
      return last.nextCursor !== null && loaded < last.total ? last.nextCursor : undefined;
    },
    refetchOnMount: "always",
    refetchOnReconnect: "always",
    refetchInterval: enabled ? 15_000 : false,
  });
  useEffect(
    () =>
      onRoomChange((event) => {
        if (
          isCurrentScope() &&
          event.conversationId === sourceConversationId &&
          event.accountId === accountId &&
          event.organizationId === organizationId
        ) {
          void client.invalidateQueries({
            queryKey: qk.roomThreadContext.source(
              accountId,
              organizationId,
              tenant,
              sourceConversationId,
            ),
          });
        }
      }),
    [client, accountId, isCurrentScope, organizationId, tenant, sourceConversationId],
  );
  const messages = useMemo(() => mergeSourceMessages(query.data?.pages ?? []), [query.data?.pages]);
  return { ...query, messages };
}

/** Candidate rows are fetched only when a manager opens the editor. */
export function useRoomThreadContextCandidates(
  conversationId: string | null,
  rootMessageId: string | null,
  contextRevision: number | null,
  enabled = true,
  sourceConversationId: string | null = null,
) {
  const identity = useRoomIdentity();
  const { accountId, organizationId, tenant, current: isCurrentScope } = identity;
  const client = useQueryClient();
  const queryKey = qk.roomThreadContext.candidate(
    identity.accountId,
    identity.organizationId,
    identity.tenant,
    conversationId,
    rootMessageId,
    contextRevision,
  );
  const query = useQuery({
    queryKey,
    queryFn: async () => {
      if (!identity.current() || conversationId === null || rootMessageId === null)
        throw new Error("ROOM_THREAD_CONTEXT_SCOPE_CHANGED");
      const result = await getRoomThreadContextCandidates(conversationId, rootMessageId);
      if (!identity.current()) throw new Error("ROOM_THREAD_CONTEXT_SCOPE_CHANGED");
      if (sourceConversationId !== null && result.source_conversation_id !== sourceConversationId) {
        throw new Error("ROOM_THREAD_CONTEXT_CANDIDATES_SCOPE_MISMATCH");
      }
      return result;
    },
    enabled:
      enabled &&
      conversationId !== null &&
      rootMessageId !== null &&
      contextRevision !== null &&
      identity.accountId !== undefined &&
      identity.tenant !== null,
    refetchOnMount: "always",
    refetchOnReconnect: "always",
  });
  useEffect(
    () =>
      onRoomChange((event) => {
        if (
          isCurrentScope() &&
          (event.conversationId === conversationId ||
            event.conversationId === sourceConversationId) &&
          event.accountId === accountId &&
          event.organizationId === organizationId
        ) {
          void client.invalidateQueries({
            queryKey: qk.roomThreadContext.candidates(
              accountId,
              organizationId,
              tenant,
              conversationId,
              rootMessageId,
            ),
          });
        }
      }),
    [
      client,
      conversationId,
      accountId,
      isCurrentScope,
      organizationId,
      tenant,
      rootMessageId,
      sourceConversationId,
    ],
  );
  return query;
}

export function useRoomThreadContextActions(
  conversationId: string | null,
  rootMessageId: string | null = null,
  editorLifetime = 0,
) {
  const identity = useRoomIdentity();
  const queryClient = useQueryClient();
  const conversationApi = useConversationStore.useApi();
  const selectionVersion = useConversationStore((state) => state.selectionVersion);
  const [pendingWrites, setPendingWrites] = useState(0);
  const { accountId, organizationId, tenant, current } = identity;
  const scopeRef = useRef<{
    conversationId: string | null;
    rootMessageId: string | null;
    editorLifetime: number;
    selectionVersion: number;
  } | null>(null);
  useLayoutEffect(() => {
    scopeRef.current = { conversationId, rootMessageId, editorLifetime, selectionVersion };
    return () => {
      scopeRef.current = null;
    };
  }, [conversationId, rootMessageId, editorLifetime, selectionVersion]);
  const stillHere = useCallback(
    (
      expectedSelectionVersion = selectionVersion,
      expectedRootMessageId = rootMessageId,
      expectedEditorLifetime = editorLifetime,
    ) =>
      conversationId !== null &&
      current() &&
      useAuthStore.getState().user?.id === accountId &&
      useOrgStore.getState().activeOrgId === organizationId &&
      conversationApi.getState().currentConversationId === conversationId &&
      conversationApi.getState().selectionVersion === expectedSelectionVersion &&
      scopeRef.current !== null &&
      scopeRef.current.conversationId === conversationId &&
      scopeRef.current.rootMessageId === expectedRootMessageId &&
      scopeRef.current.editorLifetime === expectedEditorLifetime &&
      scopeRef.current.selectionVersion === expectedSelectionVersion,
    [
      accountId,
      conversationApi,
      conversationId,
      current,
      editorLifetime,
      organizationId,
      rootMessageId,
      selectionVersion,
    ],
  );
  const run = useCallback(
    async <T>(operation: () => Promise<T>): Promise<T | null> => {
      const expectedSelectionVersion = conversationApi.getState().selectionVersion;
      const expectedRootMessageId = rootMessageId;
      const expectedEditorLifetime = editorLifetime;
      const expectedScope = scopeRef.current;
      const operationIsCurrent = () =>
        scopeRef.current === expectedScope &&
        stillHere(expectedSelectionVersion, expectedRootMessageId, expectedEditorLifetime);
      if (!operationIsCurrent()) return null;
      setPendingWrites((count) => count + 1);
      try {
        const result = await operation();
        // The server may have committed after the user left this view. Refresh
        // the originating scope, but never let its result update the new editor.
        if (expectedRootMessageId !== null) {
          void queryClient.invalidateQueries({
            queryKey: qk.roomThreads.detail(
              accountId,
              tenant,
              conversationId,
              expectedRootMessageId,
            ),
          });
          void queryClient.invalidateQueries({
            queryKey: qk.roomThreadContext.candidates(
              accountId,
              organizationId,
              tenant,
              conversationId,
              expectedRootMessageId,
            ),
          });
        }
        void queryClient.invalidateQueries({ queryKey: qk.conversations.all() });
        if (conversationId !== null) {
          announceRoomChange({ conversationId, accountId, organizationId });
        }
        if (!operationIsCurrent()) return null;
        return result;
      } catch (error) {
        if (!operationIsCurrent()) return null;
        throw error;
      } finally {
        setPendingWrites((count) => Math.max(0, count - 1));
      }
    },
    [
      accountId,
      conversationId,
      conversationApi,
      editorLifetime,
      organizationId,
      queryClient,
      rootMessageId,
      stillHere,
      tenant,
    ],
  );
  const createFromRange = useCallback(
    (input: RoomThreadContextRangeInput) => {
      if (conversationId === null) return Promise.resolve(null);
      return run(() => createRoomThreadFromRange(conversationId, input));
    },
    [conversationId, run],
  );
  const updateContext = useCallback(
    (input: RoomThreadContextUpdateInput) => {
      if (conversationId === null || rootMessageId === null) return Promise.resolve(null);
      return run(() => updateRoomThreadContext(conversationId, rootMessageId, input));
    },
    [conversationId, rootMessageId, run],
  );
  const moveContext = useCallback(
    (input: RoomThreadContextMutationInput) => {
      if (conversationId === null || rootMessageId === null) return Promise.resolve(null);
      return run(() => moveRoomThreadContext(conversationId, rootMessageId, input));
    },
    [conversationId, rootMessageId, run],
  );
  const returnContext = useCallback(
    (input: RoomThreadContextMutationInput) => {
      if (conversationId === null || rootMessageId === null) return Promise.resolve(null);
      return run(() => returnRoomThreadContext(conversationId, rootMessageId, input));
    },
    [conversationId, rootMessageId, run],
  );
  return {
    createFromRange,
    updateContext,
    moveContext,
    returnContext,
    isPending: pendingWrites > 0,
    isCurrent: stillHere,
  };
}

/** What a successful mutation may open in the current transcript. */
export function threadRootFromAction(action: RoomThreadContextActionRead): string {
  return action.root_message_id;
}
