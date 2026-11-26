"use client";

import { useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { useAuthStore, useOrgStore } from "@/stores";
import { parseOnboarding, type StartStep } from "@/lib/onboarding-api";
import { qk } from "@/lib/query-keys";

interface StepReport {
  step: StartStep;
  userId: string;
  organizationId: string;
}

function ownsReport(report: StepReport): boolean {
  return (
    useAuthStore.getState().user?.id === report.userId &&
    useOrgStore.getState().activeOrgId === report.organizationId
  );
}

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
    // Identity changes must detach the observer from the previous account's queue.
    mutationKey: [...qk.onboarding.state(userId ?? "", organizationId ?? ""), "progress"],
    scope: { id: `onboarding-progress:${userId}:${organizationId}` },
    mutationFn: async (report: StepReport) => {
      if (!ownsReport(report)) throw new Error(errors("sessionExpired"));
      const result = await apiClient.patch<unknown>(
        "/me/onboarding",
        { current_step: report.step },
        { headers: { "X-Organization-Id": report.organizationId } },
      );
      return parseOnboarding(result);
    },
    onError: (error: unknown, report: StepReport) => {
      if (!ownsReport(report)) return;
      if (
        !current.current.mounted ||
        !current.current.enabled ||
        current.current.step !== report.step
      )
        return;
      toast.error(getErrorMessage(error, errors), {
        action: {
          label: common("retry"),
          onClick: () => {
            if (
              current.current.mounted &&
              current.current.enabled &&
              current.current.step === report.step &&
              ownsReport(report)
            )
              mutate(report);
          },
        },
      });
    },
  });
  useEffect(() => {
    if (enabled && userId && organizationId && organizationId === activeOrganizationId)
      mutate({ step, userId, organizationId });
  }, [step, organizationId, activeOrganizationId, userId, enabled, mutate]);
}
