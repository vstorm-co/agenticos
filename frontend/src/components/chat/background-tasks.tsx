"use client";

import { useState } from "react";
import { ChevronDown, GitBranch, Loader2, Square } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  useConversationTasks,
  taskIsActive,
  type ConversationTask,
} from "@/hooks/use-conversation-tasks";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Tasks stay visible across turns, with their own topic and ordinary approval queue. */
export function BackgroundTasks({ conversationId }: { conversationId: string | null }) {
  const t = useTranslations("chat.backgroundTasks");
  const state = useConversationTasks(conversationId ?? undefined);
  const [expanded, setExpanded] = useState(false);
  const tasks = state.data ?? [];
  if (tasks.length === 0) {
    if (state.error)
      return (
        <Button variant="ghost" size="sm" onClick={() => void state.refetch()}>
          {t("retry")}
        </Button>
      );
    return null;
  }
  const active = tasks.filter(taskIsActive).length;
  return (
    <section
      className="border-foreground/8 mb-2 overflow-hidden rounded-xl border"
      data-tour="chat-background-tasks"
    >
      <button
        type="button"
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px]"
        onClick={() => setExpanded(!expanded)}
      >
        {active > 0 ? (
          <Loader2 className="size-3.5 shrink-0 animate-spin" />
        ) : (
          <GitBranch className="size-3.5 shrink-0" />
        )}
        <span className="min-w-0 flex-1 truncate">{t("heading", { count: active })}</span>
        <ChevronDown
          className={cn("size-3.5 shrink-0 transition-transform", expanded && "rotate-180")}
        />
      </button>
      {expanded && (
        <BackgroundTaskList
          tasks={tasks}
          stopping={state.stop.isPending}
          onStop={(id) => state.stop.mutate(id)}
        />
      )}
    </section>
  );
}

export function BackgroundTaskList({
  tasks,
  stopping,
  onStop,
}: {
  tasks: ConversationTask[];
  stopping: boolean;
  onStop: (id: string) => void;
}) {
  const t = useTranslations("chat.backgroundTasks");
  return (
    <ul className="max-h-64 space-y-1 overflow-y-auto p-2">
      {tasks.map((task) => (
        <li
          key={task.id}
          className="hover:bg-muted/50 flex items-center gap-2 rounded-lg px-2 py-1.5"
        >
          <Link
            href={`/chat?id=${encodeURIComponent(task.conversation_id)}`}
            className="min-w-0 flex-1"
            title={task.title}
          >
            <span className="block truncate text-sm">{task.title}</span>
            <span className="text-muted-foreground block text-xs">
              {t(`status.${task.status}`)}
              {task.delivery === "interrupted" ? ` · ${t("returnInterrupted")}` : ""}
            </span>
          </Link>
          {taskIsActive(task) && (
            <Button
              size="icon"
              variant="ghost"
              className="size-7 shrink-0"
              aria-label={t("stop", { title: task.title })}
              disabled={stopping}
              onClick={() => onStop(task.id)}
            >
              <Square className="size-3" />
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}
