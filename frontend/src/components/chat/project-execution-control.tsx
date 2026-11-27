"use client";

import { useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ChevronDown, FolderOpen } from "lucide-react";
import { useProjectOfConversation } from "@/hooks/use-projects";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { getProject } from "@/lib/projects-api";
import { qk } from "@/lib/query-keys";
import { NATIVE_CHOICE } from "@/components/ui/control-styles";
import { NativeDisclosure } from "@/components/ui/native-disclosure";
import { Button } from "@/components/ui/button";
import { useConversationStore } from "@/stores";
import { useWorkOnStore } from "@/stores/work-on-store";

/** Project files stay shared while the agent retains its configured tools. */
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
  const executable = details.data?.backend === "service";
  return (
    <section aria-labelledby={`${id}-title`} className="space-y-2 py-1">
      <div className="flex items-center gap-2 text-xs font-medium" id={`${id}-title`}>
        <FolderOpen className="text-muted-foreground size-4 shrink-0" aria-hidden />
        <span className="min-w-0 break-words">
          {projectId && details.data && !pending && !failed
            ? details.data.name
            : t(projectId || pending || failed ? "title" : "workspace")}
        </span>
      </div>
      {!failed && (
        <p className="text-muted-foreground text-xs leading-5">
          {t(
            pending
              ? "loading"
              : !projectId && !failed
                ? "noProject"
                : onComputer
                  ? "local"
                  : !hasCommands
                    ? "filesOnly"
                    : executable
                      ? "hint"
                      : "projectFilesOnly",
          )}
        </p>
      )}
      {failed ? (
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
      ) : hasCommands && !onComputer && !pending && projectId ? (
        <NativeDisclosure className="group">
          <summary className="text-muted-foreground flex min-h-9 cursor-pointer list-none items-center gap-2 text-xs [&::-webkit-details-marker]:hidden">
            <ChevronDown
              className="size-3.5 -rotate-90 transition-transform group-open:rotate-0"
              aria-hidden
            />
            {t("advanced")}
            {selected !== null && <span className="text-foreground ml-auto">{t(selected)}</span>}
          </summary>
          <fieldset className="space-y-1 pt-1">
            <legend className="sr-only">{t("commandTarget")}</legend>
            {(["automatic", "agent", "project"] as const).map((target) => (
              <label key={target} className="flex min-h-10 items-center gap-3 text-xs">
                <input
                  className={NATIVE_CHOICE}
                  type="radio"
                  name={id}
                  value={target}
                  checked={target === "automatic" ? selected === null : selected === target}
                  disabled={target === "project" && !executable}
                  onChange={() =>
                    setExecution(conversationId, projectId, target === "automatic" ? null : target)
                  }
                />
                {t(target)}
              </label>
            ))}
            <p className="text-muted-foreground pt-1 text-xs leading-5">{t("overrideHint")}</p>
          </fieldset>
        </NativeDisclosure>
      ) : null}
    </section>
  );
}
