"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { useAgentSelectionStore } from "@/stores/agent-selection-store";
import { useConversationStore } from "@/stores/conversation-store";
import { useWorkOnStore } from "@/stores/work-on-store";
import type { Conversation } from "@/types/conversation";

type Create = (
  title?: string,
  options?: { projectId?: string | null },
) => Promise<Conversation | null>;

function selection(): string {
  const auth = useAuthStore.getState();
  return JSON.stringify([
    auth.sessionOwnerId ?? auth.user?.id,
    auth.user?.id,
    useOrgStore.getState().activeOrgId,
    useAgentSelectionStore.getState().selectedAgentId,
    useConversationStore.getState().pendingProjectId,
  ]);
}

/** Opening a workspace can file the empty chat, without sending a message or invoking a model. */
export function useEnvironmentConversation(create: Create) {
  // Subscribe to the identity used by selection(); callbacks from an old scope
  // can finish their request but must never adopt its conversation in a new one.
  const actor = useAuthStore((state) => state.user?.id);
  const owner = useAuthStore((state) => state.sessionOwnerId ?? state.user?.id);
  const org = useOrgStore((state) => state.activeOrgId);
  const agent = useAgentSelectionStore((state) => state.selectedAgentId);
  const project = useConversationStore((state) => state.pendingProjectId);
  const scope = JSON.stringify([owner, actor, org, agent, project]);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const pending = useRef(new Map<string, Promise<string | null>>());
  const [opening, setOpening] = useState<readonly string[]>([]);
  const prepare = useCallback((): Promise<string | null> => {
    if (!mounted.current || selection() !== scope) return Promise.resolve(null);
    const conversation = useConversationStore.getState();
    if (conversation.currentConversationId !== null)
      return Promise.resolve(conversation.currentConversationId);
    const existing = pending.current.get(scope);
    if (existing) return existing;
    setOpening((current) => [...current, scope]);
    // Reserve the promise before invoking the caller, including a synchronous
    // throw from an adapter, so every exit releases the same pending entry.
    const request = Promise.resolve().then(async () => {
      try {
        if (!mounted.current || selection() !== scope) return null;
        const created = await create(undefined, { projectId: conversation.pendingProjectId });
        if (
          created === null ||
          !mounted.current ||
          selection() !== scope ||
          useConversationStore.getState().currentConversationId !== null
        )
          return null;
        useWorkOnStore.getState().adopt(created.id);
        useConversationStore.getState().adoptCreatedConversation(created.id);
        useConversationStore.getState().setPendingProjectId(null);
        return created.id;
      } finally {
        pending.current.delete(scope);
        if (mounted.current) setOpening((current) => current.filter((item) => item !== scope));
      }
    });
    pending.current.set(scope, request);
    return request;
  }, [create, scope]);
  return { prepare, preparing: opening.includes(scope) };
}
