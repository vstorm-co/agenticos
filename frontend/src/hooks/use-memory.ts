"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import type { MemoryErasureResult } from "@/types/memory";

/**
 * Erasing memory — the only thing a person does to it from the console.
 *
 * There is no listing hook and no editor, deliberately: what an agent wrote down
 * about a named colleague is not a screen anybody should be able to page through,
 * and standing knowledge a person authors belongs in context files. So the whole
 * surface is two deletions.
 *
 * Neither invalidates a query, because nothing here reads memory. What they
 * change is a store only an agent sees.
 */

/** Forget everything every agent in this organization knows about one person. */
export function useForgetPersonMemory() {
  const t = useTranslations("memory");
  const tErrors = useTranslations("errors");

  return useMutation({
    mutationFn: (userId: string) =>
      apiClient.delete<MemoryErasureResult>(`/memory/person/${userId}`),
    onSuccess: (result) => toast.success(t("forgottenToast", { count: result.notes_deleted })),
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });
}

/** Delete every note one agent holds, in every store. */
export function useClearAgentMemory(agentId: string) {
  const t = useTranslations("memory");
  const tErrors = useTranslations("errors");

  return useMutation({
    mutationFn: () =>
      apiClient.delete<MemoryErasureResult>(`/memory?agent_id=${encodeURIComponent(agentId)}`),
    onSuccess: (result) => toast.success(t("clearedToast", { count: result.notes_deleted })),
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });
}
