"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type { ContextChange, ContextChangeList } from "@/types/authoring";

/**
 * The context file changes the assistant proposed, and the two decisions on one.
 *
 * Both decisions invalidate the context files as well: applying rewrites a file
 * every bound agent reads on its next run, and a page left showing the old body
 * would show something no agent is reading any more.
 */
export function useContextChanges(status: "pending" | "applied" | "discarded" = "pending") {
  const tErrors = useTranslations("errors");
  const t = useTranslations("authoring.contextChanges");
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: qk.contextChanges.list(status),
    queryFn: () => apiClient.get<ContextChangeList>("/context-changes", { params: { status } }),
  });

  const invalidate = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.contextChanges.all() }),
      queryClient.invalidateQueries({ queryKey: qk.context.all() }),
      queryClient.invalidateQueries({ queryKey: qk.authoring.waiting() }),
    ]);
  }, [queryClient]);

  const applied = useMutation({
    mutationFn: (id: string) => apiClient.post<ContextChange>(`/context-changes/${id}/apply`),
    onSuccess: async (change) => {
      await invalidate();
      toast.success(t("applied", { name: change.context_name }));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });
  const discarded = useMutation({
    mutationFn: (id: string) => apiClient.post<ContextChange>(`/context-changes/${id}/discard`),
    onSuccess: async (change) => {
      await invalidate();
      toast.success(t("discarded", { name: change.context_name }));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return {
    changes: query.data?.items ?? [],
    isLoading: query.isLoading,
    error: query.error ? getErrorMessage(query.error, tErrors) : null,
    apply: (id: string) => applied.mutate(id),
    discard: (id: string) => discarded.mutate(id),
    isDeciding: applied.isPending || discarded.isPending,
  };
}
