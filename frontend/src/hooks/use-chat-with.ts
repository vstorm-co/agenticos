"use client";

import { useEffect } from "react";
import { useSearchParams } from "next/navigation";

import { setUrlParam } from "@/lib/utils";
import { useAgentSelectionStore, useConversationStore } from "@/stores";

/**
 * `/chat?with=<agent id>`: a new chat with that agent - what a pinned agent
 * opens, from the Dock's menu, the tray or a phone's home screen (#2305,
 * #2097). The agent is selected and the open thread let go, as "Chat" on the
 * agent's page does, and the parameter is taken off the address so a reload
 * does not start another.
 */
export function useChatWith(): void {
  const agentId = useSearchParams().get("with");
  const select = useAgentSelectionStore((state) => state.select);
  const resetConversation = useConversationStore((state) => state.reset);

  useEffect(() => {
    if (!agentId) return;
    select(agentId);
    resetConversation();
    setUrlParam("with", null);
  }, [agentId, select, resetConversation]);
}
