"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { LocalTarget } from "@/lib/desktop/commands";

/** Local UI preferences, never part of the shared project's server record. */
export function projectFolderKey(
  userId: string | null,
  organizationId: string | null,
  projectId: string,
): string | null {
  return userId && organizationId ? JSON.stringify([userId, organizationId, projectId]) : null;
}

interface ProjectFoldersState {
  byProject: Record<string, LocalTarget>;
  bind: (key: string, target: LocalTarget | null) => void;
}

export const useProjectFoldersStore = create<ProjectFoldersState>()(
  persist(
    (set) => ({
      byProject: {},
      bind: (key, target) =>
        set((state) => {
          const { [key]: _previous, ...rest } = state.byProject;
          return { byProject: target === null ? rest : { ...rest, [key]: target } };
        }),
    }),
    { name: "project-folders", version: 1 },
  ),
);
