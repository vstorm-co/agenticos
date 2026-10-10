"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";
import type { AssistantState, AssistantUpdate } from "@/types/assistant";

/**
 * The organization's AI Architect (#2063). Reading it installs it the first time
 * anybody in the organization opens the console, so the widget never has to.
 */
export function useAssistant() {
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const { data, isLoading } = useQuery({
    queryKey: qk.assistant(orgId),
    queryFn: () => apiClient.get<AssistantState>("/assistant"),
    enabled: orgId !== "",
  });
  return { assistant: data ?? null, isLoading };
}

/** Change the assistant's name, greeting, model or knowledge, or switch it off. */
export function useUpdateAssistant() {
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const queryClient = useQueryClient();
  const tErrors = useTranslations("errors");
  return useMutation({
    mutationFn: (update: AssistantUpdate) => apiClient.patch<AssistantState>("/assistant", update),
    onSuccess: (state) => queryClient.setQueryData(qk.assistant(orgId), state),
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });
}
