"use client";

import { create } from "zustand";

interface ChatPanelState {
  browserOpen: boolean;
  setBrowserOpen: (open: boolean) => void;
  filesOpen: boolean;
  setFilesOpen: (open: boolean) => void;
}

/** Temporary main-console layout pressure; never a saved sidebar preference. */
export const useChatPanelStore = create<ChatPanelState>((set) => ({
  browserOpen: false,
  setBrowserOpen: (browserOpen) => set({ browserOpen }),
  filesOpen: false,
  setFilesOpen: (filesOpen) => set({ filesOpen }),
}));
