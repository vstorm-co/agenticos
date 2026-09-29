"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  createTableTrigger,
  deleteTableTrigger,
  listTableTriggerAdmissions,
  listTableTriggers,
  updateTableTrigger,
} from "@/lib/table-triggers-api";
import type { TableTriggerCreate, TableTriggerUpdate } from "@/types/tables";

/** A table's triggers, and every write to them. */
export function useTableTriggers(tableId: string) {
  const t = useTranslations("pages.tables.triggers");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const key = qk.tables.triggers(tableId);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: key });
  const fail = (error: unknown) => toast.error(getErrorMessage(error, tErrors));

  const { data, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => listTableTriggers(tableId),
  });
  const create = useMutation({
    mutationFn: (body: TableTriggerCreate) => createTableTrigger(tableId, body),
    onSuccess: () => {
      refresh();
      toast.success(t("created"));
    },
    onError: fail,
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: TableTriggerUpdate }) =>
      updateTableTrigger(tableId, id, body),
    onSuccess: refresh,
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteTableTrigger(tableId, id),
    onSuccess: () => {
      refresh();
      toast.success(t("deleted"));
    },
    onError: fail,
  });
  return { triggers: data?.items ?? [], isLoading, create, update, remove };
}

/** What each added record led to, for one trigger - read while its history is open. */
export function useTableTriggerAdmissions(tableId: string, triggerId: string) {
  const { data, isLoading } = useQuery({
    queryKey: qk.tables.triggerAdmissions(tableId, triggerId),
    queryFn: () => listTableTriggerAdmissions(tableId, triggerId),
  });
  return { admissions: data?.items ?? [], total: data?.total ?? 0, isLoading };
}
