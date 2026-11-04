"use client";

import { useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";

import { setUrlParam } from "@/lib/utils";
import { useAgentSelectionStore } from "@/stores";
import { useConversations } from "@/hooks/use-conversations";

/**
 * Explicit new-chat links from the desktop shell and pinned agents. Plain /chat
 * resumes the open thread. Each ?new= request starts fresh through the same
 * action as the console's button, including when this page is already mounted.
 */
export function useChatWith(): void {
  const params = useSearchParams();
  const agentId = params.get("with");
  const request = params.get("new");
  const select = useAgentSelectionStore((state) => state.select);
  const { startNewChat } = useConversations();
  const consumed = useRef<string | null>(null);

  useEffect(() => {
    const key = request || agentId;
    if (!key) {
      consumed.current = null;
      return;
    }
    if (consumed.current === key) return;
    consumed.current = key;
    void startNewChat();
    if (agentId) select(agentId);
    if (request) setUrlParam("new", null);
    if (agentId) setUrlParam("with", null);
  }, [request, agentId, select, startNewChat]);
}
