"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { useTenantGuard, useTenantId } from "@/hooks/use-organizations";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  createDurableTask,
  ensureTaskBoard,
  listDurableTasks,
  listTaskBoards,
  updateDurableTask,
  type DurableTask,
  type TaskScope,
  type TaskStatus,
} from "@/lib/tasks-api";
import { useAuthStore } from "@/stores/auth-store";

export function useDurableTasks(tableId?: string, skip = 0) {
  const tenant = useTenantId();
  const guard = useTenantGuard();
  const user = useAuthStore((state) => state.user?.id);
  const scope = `${user ?? "-"}:${tenant ?? "-"}`;
  const client = useQueryClient();
  const errors = useTranslations("errors");
  const boards = useQuery({
    queryKey: qk.durableTasks.boards(scope),
    queryFn: ({ signal }) => listTaskBoards(signal),
    enabled: !!tenant && !!user,
  });
  const records = useQuery({
    queryKey: qk.durableTasks.records(scope, tableId, skip),
    queryFn: ({ signal }) => listDurableTasks(tableId ?? "", skip, signal),
    enabled: !!tenant && !!user && !!tableId,
    refetchInterval: 15000,
  });
  const current = () => guard(tenant) && useAuthStore.getState().user?.id === user;
  const invalidate = () => {
    if (current()) {
      void client.invalidateQueries({ queryKey: qk.durableTasks.all(scope) });
      void client.invalidateQueries({ queryKey: qk.tables.all() });
      void client.invalidateQueries({ queryKey: qk.outcomes.all() });
      void client.invalidateQueries({ queryKey: qk.suggestions.mine() });
      void client.invalidateQueries({ queryKey: qk.notifications.all() });
    }
  };
  const failure = (error: Error) => {
    if (current()) toast.error(getErrorMessage(error, errors));
  };
  const ensure = useMutation({
    mutationFn: ({ kind, id }: { kind: TaskScope; id?: string }) => ensureTaskBoard(kind, id),
    onSuccess: invalidate,
    onError: failure,
  });
  const create = useMutation({ mutationFn: createDurableTask, onSuccess: invalidate });
  const update = useMutation({
    mutationFn: ({ task, status }: { task: DurableTask; status: TaskStatus }) =>
      updateDurableTask(task, status),
    onSuccess: invalidate,
    onError: failure,
  });
  return { boards, records, ensure, create, update };
}
