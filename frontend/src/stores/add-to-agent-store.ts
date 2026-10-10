"use client";

import { create } from "zustand";

import type { AgentResourceRef } from "@/lib/agent-spec";

interface AddToAgentOffer {
  resource: AgentResourceRef;
  /** What the resource is called, for the confirmation. */
  name: string;
}

interface AddToAgentState {
  /** The resource somebody just made and chose to give an agent, or null. */
  offer: AddToAgentOffer | null;
  open: (offer: AddToAgentOffer) => void;
  close: () => void;
}

/**
 * "Add it to an agent?" from the toast that says a skill, a context file, a
 * knowledge base or an organization MCP server was created (#2072). The toast outlives the dialog that made
 * the resource, so what to add is held here and one dialog in the layout reads it.
 */
export const useAddToAgentStore = create<AddToAgentState>((set) => ({
  offer: null,
  open: (offer) => set({ offer }),
  close: () => set({ offer: null }),
}));
