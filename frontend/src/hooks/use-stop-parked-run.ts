"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";

/** The server decides who may stop a waiting run, including its initiator. */
export function useStopParkedRun(runId: string, waiting: boolean) {
  const client = useQueryClient();
  const t = useTranslations("errors");
  const org = useOrgStore((state) => state.activeOrgId);
  const user = useAuthStore((state) => state.user?.id ?? null);
  const authority = useQuery({
    queryKey: qk.runs.canStop(org, user, runId),
    queryFn: ({ signal }) => apiClient.get<boolean>(`/runs/${runId}/can-stop`, { signal }),
    enabled: waiting,
  });
  const stop = useMutation({
    mutationFn: () => apiClient.post<string | null>(`/runs/${runId}/cancel`),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: qk.runs.all() }),
        client.invalidateQueries({ queryKey: qk.triggers.all() }),
      ]);
    },
    onError: (error) => toast.error(getErrorMessage(error, t)),
  });
  return {
    canStop: waiting && authority.isSuccess && !authority.isFetching && authority.data === true,
    stop,
  };
}
