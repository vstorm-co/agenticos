"use client";

import { useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useOrgStore } from "@/stores";
import { parseOnboarding, type StartStep } from "@/lib/onboarding-api";

/** Serialize reported positions across mounted steps; progress never proves completion. */
export function useReportStartStep(step: StartStep, organizationId: string | null, enabled = true) {
  const userId = useAuthStore((state) => state.user?.id);
  const activeOrganizationId = useOrgStore((state) => state.activeOrgId);
  const client = useQueryClient();
  const errors = useTranslations("errors");
  const common = useTranslations("common");
  const { mutate } = useMutation({
    scope: { id: `onboarding-progress:${userId}:${organizationId}` },
    mutationFn: async (currentStep: StartStep) => {
      if (
        !userId ||
        !organizationId ||
        useAuthStore.getState().user?.id !== userId ||
        useOrgStore.getState().activeOrgId !== organizationId
      )
        throw new Error(errors("sessionExpired"));
      const result = await apiClient.patch<unknown>(
        "/me/onboarding",
        { current_step: currentStep },
        { headers: { "X-Organization-Id": organizationId } },
      );
      return parseOnboarding(result);
    },
    onSuccess: (data) => {
      if (userId && organizationId && useAuthStore.getState().user?.id === userId)
        client.setQueryData(qk.onboarding.state(userId, organizationId), data);
    },
    onError: (error: unknown, currentStep: StartStep) => {
      if (
        useAuthStore.getState().user?.id !== userId ||
        useOrgStore.getState().activeOrgId !== organizationId
      )
        return;
      toast.error(getErrorMessage(error, errors), {
        action: { label: common("retry"), onClick: () => mutate(currentStep) },
      });
    },
  });
  useEffect(() => {
    if (enabled && userId && organizationId && organizationId === activeOrganizationId)
      mutate(step);
  }, [step, organizationId, activeOrganizationId, userId, enabled, mutate]);
}
