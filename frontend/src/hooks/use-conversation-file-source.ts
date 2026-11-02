"use client";

import { useWorkOnStore } from "@/stores/work-on-store";
import { isDesktopShell } from "@/lib/desktop/shell";
import type { FileSource } from "@/lib/workspace-files";
import { useShell } from "./use-shell";

/** File links and the Files panel must reach the same conversation workspace. */
export function useConversationFileSource(conversationId: string | null): FileSource | null {
  const shell = useShell();
  const target = useWorkOnStore((state) => state.targetFor(conversationId));
  if (isDesktopShell(shell) && target && !target.computer_grant)
    return { kind: "local", root: target.folder };
  return conversationId === null ? null : { kind: "conversation", id: conversationId };
}
