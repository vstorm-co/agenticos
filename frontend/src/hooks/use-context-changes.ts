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
 * would show something no agent is reading any more. A refused decision reads
 * them again too - a file edited since turns its change stale, and a proposal
 * a newer run rewrote comes back at its new revision.
 */
export function useContextChanges(
  status: "pending" | "applied" | "discarded" = "pending",
  { enabled = true } = {},
) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("authoring.contextChanges");
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: qk.contextChanges.list(status),
    queryFn: () => apiClient.get<ContextChangeList>("/context-changes", { params: { status } }),
    enabled,
  });

  const invalidate = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.contextChanges.all() }),
      queryClient.invalidateQueries({ queryKey: qk.context.all() }),
      queryClient.invalidateQueries({ queryKey: qk.authoring.waiting() }),
    ]);
  }, [queryClient]);

  const applied = useMutation({
    mutationFn: (change: ContextChange) =>
      apiClient.post<ContextChange>(`/context-changes/${change.id}/apply`, {
        revision: change.revision,
      }),
    onSuccess: async (change) => {
      await invalidate();
      toast.success(t("applied", { name: change.context_name }));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, tErrors));
      void invalidate();
    },
  });
  const discarded = useMutation({
    mutationFn: (change: ContextChange) =>
      apiClient.post<ContextChange>(`/context-changes/${change.id}/discard`, {
        revision: change.revision,
      }),
    onSuccess: async (change) => {
      await invalidate();
      toast.success(t("discarded", { name: change.context_name }));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, tErrors));
      void invalidate();
    },
  });

  return {
    changes: query.data?.items ?? [],
    isLoading: query.isLoading,
    error: query.error ? getErrorMessage(query.error, tErrors) : null,
    apply: (change: ContextChange) => applied.mutate(change),
    discard: (change: ContextChange) => discarded.mutate(change),
    isDeciding: applied.isPending || discarded.isPending,
  };
}
