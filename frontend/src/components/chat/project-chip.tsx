"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { FolderKanban, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";

import { ProjectPickerDialog } from "@/components/projects/project-picker-dialog";
import { getProject } from "@/lib/projects-api";
import { apiClient } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { qk } from "@/lib/query-keys";
import { setUrlParam } from "@/lib/utils";
import { useAgentSelectionStore, useConversationStore } from "@/stores";
import type { Conversation } from "@/types/conversation";

/**
 * The project a chat is in, beside who answers it.
 *
 * Before the first message it is a choice - picked from the `+`, or arriving as
 * `?project=` from a project's New chat - and can be dropped. Once the chat
 * exists it is a fact, and a link to the project's files and instructions.
 */
export function ProjectChip({
  conversationId,
  pickerOpen,
  onPickerOpenChange,
}: {
  conversationId: string | null;
  pickerOpen: boolean;
  onPickerOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("projects");
  const searchParams = useSearchParams();
  const pending = useConversationStore((state) => state.pendingProjectId);
  const setPending = useConversationStore((state) => state.setPendingProjectId);
  const selectAgent = useAgentSelectionStore((state) => state.select);
  const [arrived] = useState(() => searchParams.get("project"));

  const { data: started } = useQuery({
    queryKey: [...qk.conversations.all(), "project-of", conversationId ?? ""] as const,
    queryFn: () => apiClient.get<Conversation>(`/conversations/${conversationId}`),
    enabled: conversationId !== null,
    select: (conversation) => conversation.project_id ?? null,
  });
  const projectId = conversationId === null ? pending : (started ?? null);

  const { data: project } = useQuery({
    queryKey: qk.projects.detail(projectId ?? ""),
    queryFn: () => getProject(projectId as string),
    enabled: projectId !== null,
    retry: false,
  });

  // A project's New chat: start in it, with its default agent, once.
  useEffect(() => {
    if (arrived === null) return;
    setPending(arrived);
    setUrlParam("project", null);
  }, [arrived, setPending]);
  useEffect(() => {
    if (conversationId === null && project?.default_agent_id && project.id === arrived) {
      selectAgent(project.default_agent_id);
    }
  }, [arrived, conversationId, project, selectAgent]);

  return (
    <>
      {projectId !== null && project && (
        <span className="bg-muted text-foreground inline-flex h-7 max-w-48 items-center gap-1.5 rounded-full pr-1 pl-2.5 text-xs">
          <FolderKanban className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <Link href={ROUTES.PROJECT_DETAIL(project.id)} className="truncate hover:underline">
            {project.name}
          </Link>
          {conversationId === null && (
            <button
              type="button"
              aria-label={t("leaveProject", { name: project.name })}
              onClick={() => setPending(null)}
              className="text-muted-foreground hover:text-foreground rounded-full p-0.5"
            >
              <X className="h-3 w-3" aria-hidden />
            </button>
          )}
        </span>
      )}
      <ProjectPickerDialog
        open={pickerOpen}
        onOpenChange={onPickerOpenChange}
        selectedId={pending}
        onPick={(picked) => {
          setPending(picked?.id ?? null);
          if (picked?.default_agent_id) selectAgent(picked.default_agent_id);
        }}
      />
    </>
  );
}
