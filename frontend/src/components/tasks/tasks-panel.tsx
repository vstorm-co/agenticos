"use client";

import { useState } from "react";
import { useTenantId } from "@/hooks/use-organizations";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { ArrowUpRight, Check, ListTodo, Plus } from "lucide-react";
import {
  Button,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ErrorState, LoadingState } from "@/components/states";
import { useDurableTasks } from "@/hooks/use-durable-tasks";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import { useAuthStore } from "@/stores/auth-store";
import { CreateTaskDialog } from "./create-task-dialog";

export function TasksPanel() {
  const tenant = useTenantId();
  const user = useAuthStore((state) => state.user?.id);
  return <TasksView key={`${tenant}:${user}`} />;
}

function TasksView() {
  const t = useTranslations("durableTasks");
  const locale = useLocale();
  const [selected, setSelected] = useState<string>();
  const [skip, setSkip] = useState(0);
  const [creating, setCreating] = useState(false);
  const user = useAuthStore((state) => state.user?.id);
  const { can } = usePermissions();
  const tasks = useDurableTasks();
  const board = tasks.boards.data?.find((item) => item.table_id === selected);
  const activeBoard =
    board ??
    tasks.boards.data?.find((item) => item.scope_kind === "private" && item.scope_id === user);
  const lostSelection = selected !== undefined && tasks.boards.data !== undefined && !board;
  const selectedTasks = useDurableTasks(activeBoard?.table_id, lostSelection ? 0 : skip);
  if (lostSelection) {
    setSelected(undefined);
    setSkip(0);
  }
  const records = selectedTasks.records;
  return (
    <section className="bg-card flex min-h-80 flex-col rounded-xl border" data-tour="durable-tasks">
      <div className="flex flex-wrap items-center gap-3 border-b p-4">
        <div className="min-w-48 flex-1">
          <h2 className="font-medium">{t("tasks")}</h2>
          <p className="text-muted-foreground mt-1 text-sm">{t("hint")}</p>
        </div>
        {!!tasks.boards.data?.length && (
          <Select
            value={activeBoard?.table_id}
            onValueChange={(value) => {
              setSelected(value);
              setSkip(0);
            }}
          >
            <SelectTrigger aria-label={t("board")} className="w-56">
              <SelectValue placeholder={t("board")} />
            </SelectTrigger>
            <SelectContent>
              {tasks.boards.data.map((item) => (
                <SelectItem key={item.id} value={item.table_id}>
                  {t(`scope.${item.scope_kind}`)}
                  {item.scope_kind !== "private" &&
                    ` · ${item.scope_name ?? item.scope_id.slice(0, 8)}`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        {activeBoard && (
          <Button variant="outline" asChild>
            <Link href={`/tables/${activeBoard.table_id}`}>
              {t("openTable")}
              <ArrowUpRight className="size-4" aria-hidden />
            </Link>
          </Button>
        )}
        {(activeBoard ? activeBoard.can_edit : can(Perm.tablesCreate)) && (
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" aria-hidden />
            {t("newTask")}
          </Button>
        )}
      </div>
      {tasks.boards.error || records.error ? (
        <ErrorState
          cta={{
            label: t("retry"),
            onClick: () => {
              void tasks.boards.refetch();
              if (activeBoard) void records.refetch();
            },
          }}
        />
      ) : tasks.boards.isPending || (activeBoard && records.isPending) ? (
        <LoadingState variant="skeleton-list" rows={3} />
      ) : records.data?.items.length ? (
        <ul className="divide-y px-5">
          {records.data.items.map((task) => (
            <li key={task.id} className="flex items-start gap-3 py-4">
              <ListTodo className="text-muted-foreground mt-1 size-4 shrink-0" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{task.title}</p>
                <div className="text-muted-foreground mt-1 flex flex-wrap gap-3 text-xs">
                  <span>{t(`status.${task.status}`)}</span>
                  <span>{t(`nextActor.${task.next_actor}`)}</span>
                  {task.start_at && (
                    <span>
                      {t("start")}: {new Date(task.start_at).toLocaleString(locale)}
                    </span>
                  )}
                  {task.due_at && (
                    <span>
                      {t("due")}: {new Date(task.due_at).toLocaleString(locale)}
                    </span>
                  )}
                  {task.conversation_id && (
                    <Link className="hover:underline" href={`/chat?id=${task.conversation_id}`}>
                      {t("openChat")}
                    </Link>
                  )}
                </div>
                {task.description && (
                  <p className="text-muted-foreground mt-2 line-clamp-2 text-sm">
                    {task.description}
                  </p>
                )}
              </div>
              {activeBoard?.can_edit && !["done", "cancelled"].includes(task.status) && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={selectedTasks.update.isPending}
                  onClick={() => selectedTasks.update.mutate({ task, status: "done" })}
                >
                  <Check className="size-4" aria-hidden />
                  {t("done")}
                </Button>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <div className="text-muted-foreground m-auto max-w-md px-6 py-14 text-center text-sm">
          <ListTodo className="mx-auto mb-3 size-7" aria-hidden />
          <p className="text-foreground font-medium">{t("empty")}</p>
          <p className="mt-2">{t("emptyHint")}</p>
        </div>
      )}
      {(skip > 0 || records.data?.has_more) && (
        <div className="flex justify-end gap-2 border-t p-3">
          <Button
            variant="outline"
            disabled={!skip}
            onClick={() => setSkip(Math.max(0, skip - 50))}
          >
            {t("previous")}
          </Button>
          <Button
            variant="outline"
            disabled={!records.data?.has_more}
            onClick={() => setSkip(skip + 50)}
          >
            {t("next")}
          </Button>
        </div>
      )}
      {creating && <CreateTaskDialog open onOpenChange={setCreating} board={activeBoard} />}
    </section>
  );
}
