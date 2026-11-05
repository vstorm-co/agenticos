"use client";

import { TasksPanel } from "@/components/tasks/tasks-panel";
import { BackgroundIcon } from "@/components/icons/product-icons";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { ArrowUpRight, Check, Circle, Loader2, Square } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { taskIsActive, useConversationTasks } from "@/hooks/use-conversation-tasks";
import { usePermissions } from "@/hooks/use-permissions";
import { cn, timeAgo } from "@/lib/utils";
import { Perm } from "@/types/permissions";

export default function WorkPage() {
  const t = useTranslations("workspaceHome");
  const ts = useTranslations("chat.backgroundTasks");
  const tt = useTranslations("time");
  const locale = useLocale();
  const tasks = useConversationTasks(null);
  const { can } = usePermissions();
  const [view, setView] = useState<"active" | "history">("active");
  const active = tasks.data?.filter(taskIsActive) ?? [];
  const history = tasks.data?.filter((task) => !taskIsActive(task)) ?? [];
  const visible = view === "active" ? active : history;
  return (
    <div className="flex w-full flex-1 flex-col gap-6">
      <PageHeader
        title={t("background")}
        description={t("backgroundDescription")}
        descriptionMode="summary"
        actions={
          can(Perm.agentsView) ? (
            <Button variant="outline" asChild>
              <Link href="/routines">
                {t("routines")}
                <ArrowUpRight className="size-4" aria-hidden />
              </Link>
            </Button>
          ) : undefined
        }
      />
      {can(Perm.tablesView) && <TasksPanel />}
      <section
        data-tour="workspace-background"
        className="bg-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border"
      >
        <div
          role="group"
          aria-label={t("background")}
          className="flex shrink-0 gap-6 border-b px-5 pt-4"
        >
          {(["active", "history"] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              aria-pressed={view === tab}
              onClick={() => setView(tab)}
              className={cn(
                "flex items-center gap-2 border-b-2 px-1 pb-3 text-sm",
                view === tab
                  ? "border-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground border-transparent",
              )}
            >
              {t(tab)}
              <span className="bg-muted rounded px-1.5 text-xs tabular-nums">
                {tab === "active" ? active.length : history.length}
              </span>
            </button>
          ))}
        </div>
        {tasks.isPending ? (
          <LoadingState variant="skeleton-list" rows={3} />
        ) : tasks.error ? (
          <ErrorState cta={{ label: t("retry"), onClick: () => void tasks.refetch() }} />
        ) : visible.length ? (
          <ul className="divide-y px-5">
            {visible.map((task) => (
              <li key={task.id} className="group flex items-start gap-4 py-5">
                <div className="bg-muted text-muted-foreground mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg">
                  {taskIsActive(task) ? (
                    <Loader2
                      className="size-4 animate-spin motion-reduce:animate-none"
                      aria-hidden
                    />
                  ) : task.status === "completed" ? (
                    <Check className="size-4" aria-hidden />
                  ) : (
                    <Circle className="size-4" aria-hidden />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <Link
                    href={`/chat?id=${encodeURIComponent(task.conversation_id)}`}
                    className="text-sm font-medium hover:underline"
                  >
                    {task.title}
                  </Link>
                  <div className="text-muted-foreground mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs">
                    <span>{ts(`status.${task.status}`)}</span>
                    <span>{timeAgo(task.created_at, tt, locale)}</span>
                    {task.delivery === "interrupted" && <span>{ts("returnInterrupted")}</span>}
                  </div>
                  {task.outcome && (
                    <p className="text-muted-foreground mt-3 line-clamp-3 text-sm leading-relaxed">
                      {task.outcome}
                    </p>
                  )}
                </div>
                {taskIsActive(task) && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={tasks.stop.isPending}
                    onClick={() => tasks.stop.mutate(task.id)}
                    aria-label={ts("stop", { title: task.title })}
                  >
                    <Square className="size-3" aria-hidden />
                    {t("stop")}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <div className="mx-auto flex w-full max-w-lg flex-1 flex-col items-center justify-center px-4 py-16 text-center">
            <div className="bg-muted text-muted-foreground mb-5 flex size-12 items-center justify-center rounded-2xl">
              <BackgroundIcon className="size-5" aria-hidden />
            </div>
            <h2 className="text-lg font-medium">
              {t(view === "active" ? "nothingRunning" : "noHistory")}
            </h2>
            <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
              {t(view === "active" ? "backgroundEmpty" : "historyDescription")}
            </p>
            {view === "active" && (
              <Button variant="outline" className="mt-6" asChild>
                <Link href="/chat">
                  {t("backToChat")}
                  <ArrowUpRight className="size-4" aria-hidden />
                </Link>
              </Button>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
