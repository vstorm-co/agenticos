"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface OrgState {
  // UI selection only — the orgs list itself is owned by React Query
  // (qk.organizations.list). This store persists which org the user picked.
  activeOrgId: string | null;
  /**
   * Organizations the server has refused this session.
   *
   * Deliberately not persisted: a refusal is a fact about right now — the org
   * was deleted, or the member was removed — and re-adding the member must be
   * enough to make it usable again, without anyone clearing browser storage.
   *
   * It exists because "pick an organization" and "recover from a refused one"
   * are otherwise free to disagree. The default selection and the recovery both
   * read the same list, so neither can hand the selection back to an org the
   * other has just moved off, which is the shape an infinite switch loop takes.
   */
  refusedOrgIds: readonly string[];
  setActiveOrgId: (id: string | null) => void;
  markOrgRefused: (id: string) => void;
}

export const useOrgStore = create<OrgState>()(
  persist(
    (set) => ({
      activeOrgId: null,
      refusedOrgIds: [],
      setActiveOrgId: (id) => set({ activeOrgId: id }),
      markOrgRefused: (id) =>
        set((state) =>
          state.refusedOrgIds.includes(id)
            ? state
            : { refusedOrgIds: [...state.refusedOrgIds, id] },
        ),
    }),
    {
      name: "org-storage",
      partialize: (state) => ({
        activeOrgId: state.activeOrgId,
      }),
    },
  ),
);
