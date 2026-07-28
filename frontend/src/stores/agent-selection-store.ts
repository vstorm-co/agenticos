"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Which published agent the chat is addressed to.
 *
 * `null` is the general assistant - the product the chat has always been, and
 * what the backend runs for a frame carrying no `agent_id`. There is no
 * per-organization default on either side: an unset selection means the
 * assistant, never "guess an agent".
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
