"use client";

import { useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { FolderOpen } from "lucide-react";
import { useProjectOfConversation } from "@/hooks/use-projects";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { getProject } from "@/lib/projects-api";
import { qk } from "@/lib/query-keys";
import { NATIVE_CHOICE } from "@/components/ui/control-styles";
import { Button } from "@/components/ui/button";
import { useConversationStore } from "@/stores";
import { useWorkOnStore, type ProjectExecutionTarget } from "@/stores/work-on-store";

/** A project supplies files; command execution is a separate, explicit turn choice. */
export function ProjectExecutionControl({
  agentCapabilities,
}: {
  agentCapabilities: readonly string[] | null;
}) {
  const id = useId();
  const t = useTranslations("chat.controls.projectExecution");
  const common = useTranslations("common");
  const shell = useShell();
  const conversationId = useConversationStore((state) => state.currentConversationId);
  const pendingProjectId = useConversationStore((state) => state.pendingProjectId);
  const project = useProjectOfConversation(conversationId);
  const projectId = conversationId === null ? pendingProjectId : project.data;
  const details = useQuery({
    queryKey: qk.projects.detail(projectId ?? ""),
    queryFn: () => getProject(projectId ?? ""),
    enabled: Boolean(projectId),
    retry: false,
  });
  const selected = useWorkOnStore((state) => state.executionFor(conversationId, pendingProjectId));
  const local = useWorkOnStore((state) => state.targetFor(conversationId));
  const setExecution = useWorkOnStore((state) => state.setExecution);
  const onComputer = isDesktopShell(shell) && local !== null;
  const hasCommands = agentCapabilities?.includes("sandbox") === true;
  const pending =
    (conversationId !== null && project.isPending) || (Boolean(projectId) && details.isPending);
  const failed = project.isError || (Boolean(projectId) && details.isError);
  const unavailable = failed || pending;
  const executable = details.data?.backend === "service";
  const active = unavailable
    ? null
    : onComputer
      ? "agent"
      : (selected ?? (projectId && executable ? "project" : "agent"));
  return (
    <fieldset className="border-foreground/8 space-y-3 border-b py-3">
      <legend className="flex items-center gap-2 text-[13px] font-medium">
        <FolderOpen className="text-muted-foreground size-4" aria-hidden />
        {t("title")}
      </legend>
      {!hasCommands ? (
        <p className="text-muted-foreground text-xs leading-relaxed">{t("filesOnly")}</p>
      ) : (
        <>
          <div className="space-y-1" aria-describedby={`${id}-hint`}>
            {(["agent", "project"] as const).map((target: ProjectExecutionTarget) => (
              <label key={target} className="flex min-h-11 items-center gap-3 text-xs">
                <input
                  className={NATIVE_CHOICE}
                  type="radio"
                  name={id}
                  value={target}
                  checked={active === target}
                  disabled={
                    unavailable || onComputer || !projectId || (target === "project" && !executable)
                  }
                  onChange={() => {
                    if (projectId) setExecution(conversationId, projectId, target);
                  }}
                />
                {t(target)}
              </label>
            ))}
          </div>
          <p id={`${id}-hint`} className="text-muted-foreground text-xs leading-relaxed">
            {t(
              onComputer
                ? "local"
                : pending
                  ? "loading"
                  : projectId
                    ? executable
                      ? "hint"
                      : "projectFilesOnly"
                    : "noProject",
            )}
          </p>
          {failed && (
            <div role="alert" className="space-y-2 text-xs">
              <p>{t("unavailable")}</p>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => void (project.isError ? project.refetch() : details.refetch())}
              >
                {common("retry")}
              </Button>
            </div>
          )}
        </>
      )}
    </fieldset>
  );
}
