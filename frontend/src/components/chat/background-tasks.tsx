"use client";

import { Square } from "lucide-react";
import { useTranslations } from "next-intl";
import { taskIsActive, type ConversationTask } from "@/hooks/use-conversation-tasks";
import Link from "next/link";
import { Button } from "@/components/ui/button";

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
