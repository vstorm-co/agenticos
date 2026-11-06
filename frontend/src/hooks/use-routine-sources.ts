"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { routineSourcesApi } from "@/lib/routine-sources-api";
import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/api-error";

export function useRoutineSources(agentId: string, triggerId: string) {
  const client = useQueryClient();
  const t = useTranslations("errors");
  const key = qk.triggers.sources(agentId, triggerId);
  const query = useQuery({
    queryKey: key,
    queryFn: () => routineSourcesApi.get(agentId, triggerId),
  });
  const replace = useMutation({
    mutationFn: (token: string) => routineSourcesApi.replace(agentId, triggerId, token),
    onSuccess: (data) => {
      client.setQueryData(key, data);
      void client.invalidateQueries({ queryKey: qk.triggers.all() });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, t));
      void client.invalidateQueries({ queryKey: key });
    },
  });
  return { ...query, replace };
}
