"use client";

import { create } from "zustand";

interface ArchitectMarkState {
  /** The agent that is the active organization's Architect, while it wears its shipped mark. */
  agentId: string | null;
  setAgentId: (agentId: string | null) => void;
}

/**
 * Which agent draws as the Architect's mark rather than as its stored picture.
 *
 * The mark is stored as an ordinary agent picture so every surface has one to
 * draw - but a picture is one fixed image, dark on a dark page. The console draws
 * the mark itself instead, in the theme's colours, wherever that agent appears:
 * the transcript, a picker, the catalog. Held here rather than read from the
 * query layer because an avatar is drawn in places with no query client, and
 * written by `useAssistant`, the one reader of the assistant's state.
 */
export const useArchitectMarkStore = create<ArchitectMarkState>((set) => ({
  agentId: null,
  setAgentId: (agentId) => set({ agentId }),
}));
