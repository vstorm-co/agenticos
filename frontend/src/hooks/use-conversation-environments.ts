"use client";

import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useLayoutEffect, useMemo, useRef } from "react";

import {
  endConversationEnvironment,
  readConversationEnvironments,
  startConversationEnvironment,
  type ConversationEnvironment,
  type ConversationEnvironmentKind,
  type ConversationEnvironmentList,
  type EnvironmentExecutionTarget,
} from "@/lib/conversation-environments-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";

interface EnvironmentReadResult {
  data: ConversationEnvironmentList | undefined;
  error: unknown;
}

interface Address {
  conversation: string;
  agent: string;
  kind: ConversationEnvironmentKind;
}

interface Operation extends Address {
  scope: string;
  target: EnvironmentExecutionTarget;
}

/** Readiness is passive; only an explicit start opens a remote environment. */
export function useConversationEnvironments(
  conversationId: string | null,
  agentId: string | null,
  enabled: boolean,
  target: EnvironmentExecutionTarget = "agent",
) {
  const client = useQueryClient();
  const owner = useAuthStore((state) => state.sessionOwnerId ?? state.user?.id ?? null);
  const actor = useAuthStore((state) => state.user?.id ?? null);
  const org = useOrgStore((state) => state.activeOrgId);
  const key = useMemo(
    () => qk.conversationEnvironments.context(owner, actor, org, conversationId, agentId, target),
    [owner, actor, org, conversationId, agentId, target],
  );
  const scope = JSON.stringify(key);
  const currentScope = useRef<string | null>(scope);
  useLayoutEffect(() => {
    currentScope.current = scope;
    return () => {
      currentScope.current = null;
    };
  }, [scope]);
  const query = useQuery({
    queryKey: key,
    queryFn:
      conversationId === null || agentId === null
        ? skipToken
        : () => readConversationEnvironments(conversationId, agentId, target),
    enabled: enabled && owner !== null && actor !== null,
    retry: false,
    refetchInterval: (current) =>
      current.state.data?.items.some((item) => item.state === "starting") ? 1000 : false,
  });
  const refresh = useCallback(async (): Promise<EnvironmentReadResult | null> => {
    const active = () => {
      const identity = useAuthStore.getState();
      return (
        currentScope.current === scope &&
        owner !== null &&
        actor !== null &&
        owner === (identity.sessionOwnerId ?? identity.user?.id ?? null) &&
        actor === (identity.user?.id ?? null) &&
        org === useOrgStore.getState().activeOrgId
      );
    };
    if (conversationId === null || agentId === null || !active()) return null;
    // A new browser call must not reuse an unfinished read's earlier snapshot.
    // Capture its key and address rather than an observer's mutable selection.
    await client.cancelQueries({ queryKey: key, exact: true });
    if (!active()) return null;
    try {
      const data = await client.fetchQuery({
        queryKey: key,
        queryFn: () => readConversationEnvironments(conversationId, agentId, target),
        staleTime: 0,
        retry: false,
      });
      return active() ? { data, error: null } : null;
    } catch (error) {
      return active() ? { data: undefined, error } : null;
    }
  }, [client, key, scope, owner, actor, org, conversationId, agentId, target]);
  const start = useMutation({
    mutationFn: ({ conversation, agent, kind, target }: Operation) =>
      startConversationEnvironment(conversation, agent, kind, target),
    retry: false,
  });
  const end = useMutation({
    mutationFn: ({ conversation, agent, kind, target }: Operation) =>
      endConversationEnvironment(conversation, agent, kind, target),
    retry: false,
  });

  const remember = useCallback(
    async (value: ConversationEnvironment): Promise<void> => {
      await client.cancelQueries({ queryKey: key, exact: true });
      client.setQueryData<ConversationEnvironmentList>(key, (previous) =>
        previous === undefined
          ? undefined
          : {
              items: previous.items.map((item) =>
                item.kind === value.kind &&
                item.agent_id === value.agent_id &&
                item.id === value.id &&
                item.execution_target === value.execution_target
                  ? value
                  : item,
              ),
            },
      );
    },
    [client, key],
  );

  return {
    items: query.data?.items,
    isLoading: query.isLoading,
    error: query.error,
    refresh,
    remember,
    start: async (address: Address) => {
      const result = await start.mutateAsync({ ...address, scope, target });
      // A draft can receive its first conversation id while this request waits.
      // Populate only the exact destination cache, never the current selection.
      const destination = qk.conversationEnvironments.context(
        owner,
        actor,
        org,
        address.conversation,
        address.agent,
        target,
      );
      await client.invalidateQueries({ queryKey: destination });
      return result;
    },
    end: async (address: Address) => {
      await end.mutateAsync({ ...address, scope, target });
      await client.invalidateQueries({
        queryKey: qk.conversationEnvironments.context(
          owner,
          actor,
          org,
          address.conversation,
          address.agent,
          target,
        ),
      });
    },
    isStarting: start.isPending && start.variables.scope === scope,
    isEnding: end.isPending && end.variables.scope === scope,
  };
}
