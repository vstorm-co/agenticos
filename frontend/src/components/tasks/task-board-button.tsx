"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ListTodo } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDurableTasks } from "@/hooks/use-durable-tasks";
import { usePermissions } from "@/hooks/use-permissions";
import { useTenantGuard, useTenantId } from "@/hooks/use-organizations";
import { Perm } from "@/types/permissions";
import type { TaskScope } from "@/lib/tasks-api";

export function TaskBoardButton({ scope, scopeId }: { scope: TaskScope; scopeId?: string }) {
  const t = useTranslations("durableTasks");
  const { can } = usePermissions();
  const { ensure, boards } = useDurableTasks();
  const router = useRouter();
  const tenant = useTenantId();
  const guard = useTenantGuard();
  const existing = boards.data?.find(
    (board) => board.scope_kind === scope && (!scopeId || board.scope_id === scopeId),
  );
  if (!existing && !can(Perm.tablesCreate)) return null;
  return (
    <Button
      variant="outline"
      disabled={ensure.isPending}
      onClick={() => {
        if (existing) router.push(`/tables/${existing.table_id}`);
        else
          ensure.mutate(
            { kind: scope, id: scopeId },
            {
              onSuccess: (board) => {
                if (guard(tenant)) router.push(`/tables/${board.table_id}`);
              },
            },
          );
      }}
    >
      <ListTodo className="size-4" aria-hidden />
      {t("tasks")}
    </Button>
  );
}
