"use client";
import { create } from "zustand";
import { persist } from "zustand/middleware";
interface ReleaseNotesState {
  acknowledged: Record<string, string>;
  acknowledge: (userId: string, version: string) => void;
}
export const useReleaseNotesStore = create<ReleaseNotesState>()(
  persist(
    (set) => ({
      acknowledged: {},
      acknowledge: (userId, version) =>
        set((state) => ({ acknowledged: { ...state.acknowledged, [userId]: version } })),
    }),
    { name: "release-notes" },
  ),
);
