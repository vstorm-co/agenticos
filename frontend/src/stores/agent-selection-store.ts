"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Which published agent the chat is addressed to.
 *
 * `null` means no agent has been chosen yet - a fresh browser, or a selection
 * pointing at an agent that has since been unpublished. The chat offers only
 * published agents, so the picker resolves `null` to the first one as soon as
 * the list arrives rather than leaving the composer unaddressed.
 *
 * Persisted to localStorage the same way the knowledge-base draft is, so the
 * choice survives a refresh or a new tab. Only the id is kept: the name is
 * server state and is resolved where it is rendered, so a renamed agent does
 * not keep answering under its old label.
 */
interface AgentSelectionState {
  selectedAgentId: string | null;
  select: (agentId: string | null) => void;
}

export const useAgentSelectionStore = create<AgentSelectionState>()(
  persist(
    (set) => ({
      selectedAgentId: null,
      select: (agentId) => set({ selectedAgentId: agentId }),
    }),
    {
      name: "agent-selection",
      version: 1,
    },
  ),
);
