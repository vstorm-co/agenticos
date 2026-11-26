"use client";

import { create } from "zustand";

interface ChatPanelState {
  filesOpen: boolean;
  setFilesOpen: (open: boolean) => void;
}

/** Temporary main-console layout pressure; never a saved sidebar preference. */
export const useChatPanelStore = create<ChatPanelState>((set) => ({
  filesOpen: false,
  setFilesOpen: (filesOpen) => set({ filesOpen }),
}));
