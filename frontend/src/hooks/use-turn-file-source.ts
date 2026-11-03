"use client";

import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { useWorkOnStore } from "@/stores/work-on-store";
import { useShell } from "./use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import type { FileSource } from "@/lib/workspace-files";
import type { TurnFileSource } from "@/types/chat";

/** Other participants and computers cannot resolve a private desktop origin. */
export function useTurnFileSource(source: TurnFileSource | undefined): FileSource | null {
  const shell = useShell();
  // The persisted map is scoped by these stores; a scope change must reselect it.
  useAuthStore((state) => state.user?.id);
  useOrgStore((state) => state.activeOrgId);
  const root = useWorkOnStore((state) =>
    source?.kind === "local" ? state.fileRootFor(source.id) : undefined,
  );
  if (source?.kind === "conversation") return source;
  if (!root || !isDesktopShell(shell)) return null;
  return { kind: "local", root };
}
