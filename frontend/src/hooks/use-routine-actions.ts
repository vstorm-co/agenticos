"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { routineActionsApi, type RoutineActionKey } from "@/lib/routine-actions-api";
import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/api-error";

export function useRoutineActions(agentId: string, triggerId: string) {
  const client = useQueryClient();
  const t = useTranslations("errors");
  const key = qk.triggers.actionConsents(agentId, triggerId);
  const query = useQuery({
    queryKey: key,
    queryFn: () => routineActionsApi.get(agentId, triggerId),
  });
  const replace = useMutation({
    mutationFn: (actions: RoutineActionKey[]) =>
      routineActionsApi.replace(agentId, triggerId, actions, query.data?.review_token),
    onSuccess: (data) => client.setQueryData(key, data),
    onError: (error) => {
      toast.error(getErrorMessage(error, t));
      void client.invalidateQueries({ queryKey: key });
    },
  });
  return { ...query, replace };
}
