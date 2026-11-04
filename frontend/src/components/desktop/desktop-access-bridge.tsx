"use client";
import { useQueryClient } from "@tanstack/react-query";
import { useShellEvent } from "@/hooks/use-desktop";
import { useWorkOnStore } from "@/stores/work-on-store";
import { useProjectFoldersStore } from "@/stores/project-folders-store";
import { qk } from "@/lib/query-keys";

/** Lives across route changes, including native recovery before sign-in. */
export function DesktopAccessBridge() {
  const client = useQueryClient();
  useShellEvent("desktop:access-changed", (value) => {
    if (!value || typeof value !== "object" || !("kind" in value)) return;
    const id = "id" in value && typeof value.id === "string" ? value.id : null;
    const folder = "path" in value && typeof value.path === "string" ? value.path : null;
    const matches = (target: { folder: string; computer_grant?: string } | null) =>
      target !== null &&
      ((value.kind === "computer" && target.computer_grant === id) ||
        (value.kind === "folder" && target.folder === folder));
    const state = useWorkOnStore.getState();
    for (const [conversation, target] of Object.entries(state.byConversation))
      if (matches(target)) state.set(conversation, null);
    if (matches(state.draft)) state.set(null, null);
    const projects = useProjectFoldersStore.getState();
    for (const [key, target] of Object.entries(projects.byProject))
      if (matches(target)) projects.bind(key, null);
    void client.invalidateQueries({ queryKey: qk.desktop.local() });
    void client.invalidateQueries({ queryKey: qk.desktop.readiness() });
  });
  return null;
}
