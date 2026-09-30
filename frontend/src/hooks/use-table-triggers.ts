"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  listTableTriggerAdmissions,
  listTableTriggers,
  updateTableTrigger,
} from "@/lib/table-triggers-api";

/** A table's triggers, and pausing or resuming one - they are made by publishing. */
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
  const setActive = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      updateTableTrigger(tableId, id, { is_active: active }),
    onSuccess: (trigger) => {
      refresh();
      toast.success(trigger.is_active ? t("resumed") : t("paused"));
    },
    onError: fail,
  });
  return { triggers: data?.items ?? [], isLoading, setActive };
}

/** What each added record led to, for one trigger - read while its history is open. */
export function useTableTriggerAdmissions(tableId: string, triggerId: string) {
  const { data, isLoading } = useQuery({
    queryKey: qk.tables.triggerAdmissions(tableId, triggerId),
    queryFn: () => listTableTriggerAdmissions(tableId, triggerId),
  });
  return { admissions: data?.items ?? [], total: data?.total ?? 0, isLoading };
}
