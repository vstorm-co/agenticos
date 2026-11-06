"use client";

import { useCallback } from "react";

import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { useConversationStore } from "@/stores";
import { useLocalAccessStore } from "@/stores/local-access-store";
import { useWorkOnStore } from "@/stores/work-on-store";
import type { Agent } from "@/types/agents";

/** Whether an agent's published version works on the person's own computer. */
export function worksOnThisComputer(agent: Agent | undefined): agent is Agent {
  return agent !== undefined && (agent.local_workspace === true || !!agent.local_coding_agent);
}

/**
 * Send, once an agent that works on this computer knows where it may work.
 *
 * Such an agent has no cloud workspace, and its run fails without a folder or the
 * whole computer. The chat's own choice wins; otherwise the one remembered for
 * the agent; otherwise the person is asked once, and the answer is remembered for
 * the agent. Declining sends nothing. Anywhere but the desktop app, and for every
 * other agent, this is the send it wraps.
 */
export function useLocalAccessGate<A extends unknown[]>(
  send: (...args: A) => unknown,
  agent: Agent | undefined,
): (...args: A) => void {
  const desktop = isDesktopShell(useShell());
  return useCallback(
    (...args: A) => {
      const conversationId = useConversationStore.getState().currentConversationId;
      const workOn = useWorkOnStore.getState();
      if (!desktop || !worksOnThisComputer(agent) || workOn.targetFor(conversationId) !== null) {
        send(...args);
        return;
      }
      const remembered = workOn.agentTargetFor(agent.id);
      if (remembered !== null) {
        workOn.set(conversationId, remembered);
        send(...args);
        return;
      }
      void useLocalAccessStore
        .getState()
        .request({ id: agent.id, name: agent.name, coding: !!agent.local_coding_agent })
        .then((target) => {
          if (target === null) return;
          const store = useWorkOnStore.getState();
          store.rememberForAgent(agent.id, target);
          store.set(useConversationStore.getState().currentConversationId, target);
          send(...args);
        });
    },
    [desktop, agent, send],
  );
}
