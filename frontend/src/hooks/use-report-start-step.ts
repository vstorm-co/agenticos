"use client";

import { useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { useAuthStore, useOrgStore } from "@/stores";
import { parseOnboarding, type StartStep } from "@/lib/onboarding-api";

/** Serialize reported positions across mounted steps; progress never proves completion. */
export function useReportStartStep(step: StartStep, organizationId: string | null, enabled = true) {
  const userId = useAuthStore((state) => state.user?.id);
  const activeOrganizationId = useOrgStore((state) => state.activeOrgId);
  const current = useRef({ step, enabled, mounted: false });
  useEffect(() => {
    const context = current.current;
    context.step = step;
    context.enabled = enabled;
    context.mounted = true;
    return () => {
      context.mounted = false;
    };
  }, [step, enabled]);
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
    onError: (error: unknown, currentStep: StartStep) => {
      if (
        useAuthStore.getState().user?.id !== userId ||
        useOrgStore.getState().activeOrgId !== organizationId
      )
        return;
      if (
        !current.current.mounted ||
        !current.current.enabled ||
        current.current.step !== currentStep
      )
        return;
      toast.error(getErrorMessage(error, errors), {
        action: {
          label: common("retry"),
          onClick: () => {
            if (
              current.current.mounted &&
              current.current.enabled &&
              current.current.step === currentStep
            )
              mutate(currentStep);
          },
        },
      });
    },
  });
  useEffect(() => {
    if (enabled && userId && organizationId && organizationId === activeOrganizationId)
      mutate(step);
  }, [step, organizationId, activeOrganizationId, userId, enabled, mutate]);
}
