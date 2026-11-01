"use client";

import { create } from "zustand";

/** Something on screen holding a change that leaving would drop. */
export interface UnsavedSource {
  /** Saves the change from where it is; true when it was saved. Absent where it cannot be. */
  save?: () => Promise<boolean>;
  /** Drops the change. */
  discard: () => void;
}

/** A way out held until the person decides what happens to their changes. */
interface LeavePrompt {
  ids: string[];
  proceed: () => void;
}

export type LeaveChoice = "save" | "discard" | "stay";

export interface UnsavedChangesState {
  sources: Record<string, UnsavedSource>;
  prompt: LeavePrompt | null;
  saving: boolean;
  register: (id: string, source: UnsavedSource) => void;
  unregister: (id: string) => void;
  /**
   * Go on with `proceed` - at once when nothing unsaved stands in the way,
   * otherwise once the person has saved or discarded. `ids` narrows the
   * question to the changes this way out would drop; by default, all of them.
   */
  leave: (proceed: () => void, ids?: string[]) => void;
  answer: (choice: LeaveChoice) => Promise<void>;
}

export const useUnsavedChangesStore = create<UnsavedChangesState>((set, get) => ({
  sources: {},
  prompt: null,
  saving: false,
  register: (id, source) => set((state) => ({ sources: { ...state.sources, [id]: source } })),
  unregister: (id) =>
    set((state) => {
      const { [id]: _gone, ...rest } = state.sources;
      return { sources: rest };
    }),
  leave: (proceed, ids) => {
    const { sources } = get();
    const held = (ids ?? Object.keys(sources)).filter((id) => id in sources);
    if (held.length === 0) proceed();
    else set({ prompt: { ids: held, proceed } });
  },
  answer: async (choice) => {
    const { prompt, sources } = get();
    if (prompt === null) return;
    const held = prompt.ids.flatMap((id) => sources[id] ?? []);
    if (choice === "stay") {
      set({ prompt: null });
      return;
    }
    if (choice === "discard") {
      for (const source of held) source.discard();
      set({ prompt: null });
      prompt.proceed();
      return;
    }
    set({ saving: true });
    // In turn: the first save refused stops the rest and keeps the person where they are.
    let saved = true;
    for (const source of held) {
      if (source.save === undefined || !(await source.save())) {
        saved = false;
        break;
      }
    }
    set({ prompt: null, saving: false });
    if (saved) prompt.proceed();
  },
}));
