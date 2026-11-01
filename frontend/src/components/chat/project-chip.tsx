"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { FolderKanban, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";

import { useProjectFolder } from "@/hooks/use-project-folder";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { useWorkOnStore } from "@/stores/work-on-store";
import { ProjectPickerDialog } from "@/components/projects/project-picker-dialog";
import { useConversations } from "@/hooks/use-conversations";
import { useProjectOfConversation } from "@/hooks/use-projects";
import { getProject } from "@/lib/projects-api";
import { ROUTES } from "@/lib/constants";
import { qk } from "@/lib/query-keys";
import { setUrlParam } from "@/lib/utils";
import { useAgentSelectionStore, useConversationStore } from "@/stores";

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
  const { startNewChat } = useConversations();
  const tookArrival = useRef(false);

  const { data: started } = useProjectOfConversation(conversationId);
  const projectId = conversationId === null ? pending : (started ?? null);

  const shell = useShell();
  const local = useProjectFolder(projectId);
  const { data: project, isError: unreadable } = useQuery({
    queryKey: qk.projects.detail(projectId ?? ""),
    queryFn: () => getProject(projectId as string),
    enabled: projectId !== null,
    retry: false,
  });

  // A project's New chat: a new chat, in it, with its default agent - once. Not
  // the chat that was open before: `/chat` reopens it, and the project would
  // then name a conversation started somewhere else.
  useEffect(() => {
    if (arrived === null || tookArrival.current) return;
    tookArrival.current = true;
    void startNewChat(arrived);
    setUrlParam("project", null);
  }, [arrived, setPending, startNewChat]);
  // A choice that cannot be read - a deleted project, one no longer shared, a
  // mangled link - is dropped: kept, it drew no chip to clear it by and every
  // first message was refused for it.
  useEffect(() => {
    if (conversationId === null && pending !== null && unreadable) setPending(null);
  }, [conversationId, pending, unreadable, setPending]);
  useEffect(() => {
    if (conversationId === null && project?.default_agent_id && project.id === arrived) {
      selectAgent(project.default_agent_id);
    }
  }, [arrived, conversationId, project, selectAgent]);

  useEffect(() => {
    if (conversationId !== null || !isDesktopShell(shell) || !local.available) return;
    if (pending === null) {
      useWorkOnStore.getState().applyProject(null, null);
    } else if (local.scopeKey !== null) {
      // This personal preference is independent of metadata loading. The server
      // still checks project access before starting any local operation.
      useWorkOnStore.getState().applyProject(local.scopeKey, local.target);
    }
  }, [conversationId, shell, local.available, local.scopeKey, local.target, pending]);

  return (
    <>
      {projectId !== null && project && (
        // The agent picker's own chip beside it - its fill, its radius, a 24px
        // mark where the avatar sits - so the two read as one row of choices.
        <span className="bg-foreground/[0.06] text-foreground inline-flex max-w-48 min-w-0 items-center gap-1.5 rounded-lg py-1 pr-1.5 pl-1">
          <span className="bg-foreground/8 flex h-6 w-6 shrink-0 items-center justify-center rounded-full">
            <FolderKanban className="h-3 w-3" aria-hidden />
          </span>
          <Link
            href={ROUTES.PROJECT_DETAIL(project.id)}
            className="truncate text-sm font-medium hover:underline"
          >
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
