"use client";
import { create } from "zustand";
export interface DesktopLiveTurn {
  conversation: string;
  state: "running" | "question" | "approval";
  canStop: boolean;
}
interface State {
  turns: Record<string, DesktopLiveTurn>;
  set: (id: string, turn: DesktopLiveTurn | null) => void;
}
/** Ephemeral state of this window's sockets, including live questions not parked in the run table. */
export const useDesktopLiveStore = create<State>()((set) => ({
  turns: {},
  set: (id, turn) =>
    set((state) => {
      const { [id]: _removed, ...rest } = state.turns;
      return { turns: turn ? { ...rest, [id]: turn } : rest };
    }),
}));
