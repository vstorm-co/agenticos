"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Which published agent the chat is addressed to.
 *
 * `selectedAgentId` is the live choice. `null` means no agent has been chosen
 * yet - a fresh browser, or a selection pointing at an agent that has since
 * been unpublished. The chat offers only published agents, so the picker
 * resolves `null` to the default agent (or the first published one) as soon as
 * the list arrives rather than leaving the composer unaddressed.
 *
 * `defaultAgentId` is the user's standing preference: the agent a new chat
 * starts with. It is a fallback, not a lock - switching agents mid-thread
 * leaves it alone, and it only takes effect when a conversation begins or the
 * live selection is empty or stale.
 *
 * `selectedWorkflowId` addresses the chat to a published workflow instead: each
 * message then starts a run of it, and its answer comes back into the thread.
 * Picking an agent clears it, so exactly one of the two answers.
 *
 * Persisted to localStorage the same way the knowledge-base draft is, so the
 * choice survives a refresh or a new tab. Only ids are kept: the name is
 * server state and is resolved where it is rendered, so a renamed agent does
 * not keep answering under its old label.
 */
interface AgentSelectionState {
  selectedAgentId: string | null;
  defaultAgentId: string | null;
  selectedWorkflowId: string | null;
  select: (agentId: string | null) => void;
  setDefault: (agentId: string | null) => void;
  selectWorkflow: (workflowId: string | null) => void;
}

export const useAgentSelectionStore = create<AgentSelectionState>()(
  persist(
    (set) => ({
      selectedAgentId: null,
      defaultAgentId: null,
      selectedWorkflowId: null,
      select: (agentId) => set({ selectedAgentId: agentId, selectedWorkflowId: null }),
      setDefault: (agentId) => set({ defaultAgentId: agentId }),
      selectWorkflow: (workflowId) => set({ selectedWorkflowId: workflowId }),
    }),
    {
      name: "agent-selection",
      // Still version 1: adding `defaultAgentId` and `selectedWorkflowId` is
      // backward-compatible - a persisted state without them merges over `null`.
      version: 1,
    },
  ),
);
