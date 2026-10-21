import { create } from "zustand";

interface ArchitectAskState {
  /** The latest question handed to the Architect from elsewhere in the console. */
  asked: { id: number; text: string } | null;
  ask: (text: string) => void;
  /** Taken by the Architect's window, so a later mount does not ask it again. */
  clear: () => void;
}

/**
 * Hands a question to the Architect's window from a page that does not own it -
 * the create dialog's "Describe it" - so there is one way into the Architect.
 */
export const useArchitectAskStore = create<ArchitectAskState>((set) => ({
  asked: null,
  ask: (text) => set((state) => ({ asked: { id: (state.asked?.id ?? 0) + 1, text } })),
  clear: () => set({ asked: null }),
}));
