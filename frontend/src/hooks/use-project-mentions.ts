"use client";

import { useCallback, useMemo } from "react";

import { useAgentSelectionStore, useConversationStore } from "@/stores";
import type { Mentionable } from "@/types/mention";
import { useProjects } from "./use-projects";

/**
 * The projects `@` offers before a chat's first message, and what picking one does:
 * the chat starts in it, with its default agent - what the `+` menu's project
 * picker does, reached from the keyboard. Never sent as a mention: a chat is in a
 * project or not, and the project is the frame's `project_id`.
 */
export function useProjectMentions(enabled: boolean) {
  const { projects } = useProjects({ limit: 100, enabled });
  const setPending = useConversationStore((state) => state.setPendingProjectId);
  const selectAgent = useAgentSelectionStore((state) => state.select);

  const items = useMemo<Mentionable[]>(
    () =>
      // Only those the reader may work in, as the `+` menu's picker offers: a
      // chat started in a project shared read-only is refused at its first word.
      enabled
        ? projects
            .filter((project) => project.can_use)
            .map((project) => ({
              kind: "project",
              id: project.id,
              name: project.name,
              detail: project.description,
            }))
        : [],
    [enabled, projects],
  );

  const pick = useCallback(
    (projectId: string) => {
      setPending(projectId);
      const project = projects.find((one) => one.id === projectId);
      if (project?.default_agent_id) selectAgent(project.default_agent_id);
    },
    [projects, setPending, selectAgent],
  );

  return { items, pick };
}
