"use client";

import { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addRoomParticipant,
  createRoomConversation,
  getRoomDirectory,
  getRoomMentionables,
  getRoomParticipants,
  joinPublicRoom,
  removeRoomParticipant,
  updateRoomAgentAutoReply,
} from "@/lib/room-api";
import { qk } from "@/lib/query-keys";
import type { Conversation } from "@/types/conversation";
import type { CreateRoomConversationInput, RoomParticipantRef } from "@/types/room";
import { useRoomIdentity } from "./use-room";

export function useRoomParticipants(conversationId: string | null) {
  const identity = useRoomIdentity();
  const query = useQuery({
    queryKey: qk.roomParticipants.list(identity.accountId, identity.tenant, conversationId),
    queryFn: () => getRoomParticipants(conversationId!),
    enabled:
      conversationId !== null && identity.accountId !== undefined && identity.tenant !== null,
    refetchOnMount: "always",
    retry: false,
  });
  return {
    participants: query.data?.items ?? [],
    visibility: query.data?.visibility,
    canPost: query.data?.can_post === true,
    canManage: query.data?.can_manage === true,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}

export function useRoomMentionables(conversationId: string | null) {
  const identity = useRoomIdentity();
  const query = useQuery({
    queryKey: qk.roomParticipants.mentionables(identity.accountId, identity.tenant, conversationId),
    queryFn: () => getRoomMentionables(conversationId!),
    enabled:
      conversationId !== null && identity.accountId !== undefined && identity.tenant !== null,
    refetchOnMount: "always",
    retry: false,
  });
  return {
    mentionables: query.data?.items ?? [],
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}

function useRoomParticipantWrite<Args extends unknown[], Result>(
  conversationId: string | null,
  operation: (conversationId: string, ...args: Args) => Promise<Result>,
) {
  const identity = useRoomIdentity();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(0);
  const { accountId, tenant, current } = identity;
  const run = useCallback(
    async (...args: Args): Promise<Result | null> => {
      if (conversationId === null || accountId === undefined || tenant === null || !current())
        return null;
      setPending((count) => count + 1);
      try {
        const result = await operation(conversationId, ...args);
        if (!current()) return null;
        void queryClient.invalidateQueries({
          queryKey: qk.roomParticipants.all(accountId, tenant, conversationId),
        });
        void queryClient.invalidateQueries({ queryKey: qk.conversations.all() });
        return result;
      } catch (error) {
        if (!current()) return null;
        throw error;
      } finally {
        setPending((count) => Math.max(0, count - 1));
      }
    },
    [accountId, conversationId, current, operation, queryClient, tenant],
  );
  return { run, isPending: pending > 0 };
}

export function useAddRoomParticipant(conversationId: string | null) {
  const mutation = useRoomParticipantWrite(conversationId, addRoomParticipant);
  return {
    add: (participant: RoomParticipantRef) => mutation.run(participant),
    isAdding: mutation.isPending,
  };
}

export function useRemoveRoomParticipant(conversationId: string | null) {
  const mutation = useRoomParticipantWrite(conversationId, removeRoomParticipant);
  return {
    remove: (participant: RoomParticipantRef) => mutation.run(participant),
    isRemoving: mutation.isPending,
  };
}

export function useUpdateRoomAgentAutoReply(conversationId: string | null) {
  const mutation = useRoomParticipantWrite(conversationId, updateRoomAgentAutoReply);
  return {
    update: (agentId: string, autoReply: boolean) => mutation.run(agentId, autoReply),
    isUpdating: mutation.isPending,
  };
}

export function useRoomDirectory() {
  const identity = useRoomIdentity();
  const query = useQuery({
    queryKey: qk.roomDirectory.list(identity.accountId, identity.tenant, 0, 50),
    queryFn: () => getRoomDirectory(0, 50),
    enabled: identity.accountId !== undefined && identity.tenant !== null,
    retry: false,
  });
  return {
    rooms: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isPending,
    error: query.error,
    refetch: query.refetch,
  };
}

export function useCreateRoomConversation() {
  const identity = useRoomIdentity();
  const queryClient = useQueryClient();
  const [isCreating, setCreating] = useState(false);
  const { accountId, tenant, current } = identity;
  const create = useCallback(
    async (input: CreateRoomConversationInput): Promise<Conversation | null> => {
      if (accountId === undefined || tenant === null || !current()) return null;
      setCreating(true);
      try {
        const conversation = await createRoomConversation(input);
        if (!current()) return null;
        void queryClient.invalidateQueries({ queryKey: qk.conversations.all() });
        void queryClient.invalidateQueries({ queryKey: qk.roomDirectory.list(accountId, tenant) });
        return conversation;
      } catch (error) {
        if (!current()) return null;
        throw error;
      } finally {
        setCreating(false);
      }
    },
    [accountId, current, queryClient, tenant],
  );
  return { create, isCreating };
}

export function useJoinPublicRoom() {
  const identity = useRoomIdentity();
  const queryClient = useQueryClient();
  const [joining, setJoining] = useState(0);
  const { accountId, tenant, current } = identity;
  const join = useCallback(
    async (conversationId: string): Promise<Conversation | null> => {
      if (accountId === undefined || tenant === null || !current()) return null;
      setJoining((count) => count + 1);
      try {
        const conversation = await joinPublicRoom(conversationId);
        if (!current()) return null;
        void queryClient.invalidateQueries({ queryKey: qk.conversations.all() });
        void queryClient.invalidateQueries({ queryKey: qk.roomDirectory.list(accountId, tenant) });
        void queryClient.invalidateQueries({
          queryKey: qk.roomParticipants.all(accountId, tenant, conversationId),
        });
        return conversation;
      } catch (error) {
        if (!current()) return null;
        throw error;
      } finally {
        setJoining((count) => Math.max(0, count - 1));
      }
    },
    [accountId, current, queryClient, tenant],
  );
  return { join, isJoining: joining > 0 };
}
