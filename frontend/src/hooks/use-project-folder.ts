"use client";

import { useCallback } from "react";

import { useTenantId } from "@/hooks/use-organizations";
import { useAuthStore } from "@/stores";
import { projectFolderKey, useProjectFoldersStore } from "@/stores/project-folders-store";
import type { LocalTarget } from "@/lib/desktop/commands";

/** The current user's choice on this installation and server origin. */
export function useProjectFolder(projectId: string | null) {
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const organizationId = useTenantId();
  const key = projectId === null ? null : projectFolderKey(userId, organizationId, projectId);
  const target = useProjectFoldersStore((state) =>
    key === null ? null : (state.byProject[key] ?? null),
  );
  const bind = useCallback(
    (id: string, folder: LocalTarget | null) => {
      const scope = projectFolderKey(userId, organizationId, id);
      if (scope !== null) useProjectFoldersStore.getState().bind(scope, folder);
    },
    [userId, organizationId],
  );
  return { target, bind, available: userId !== null && organizationId !== null };
}
