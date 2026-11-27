"use client";

import { useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { useAuthStore, useOrgStore } from "@/stores";
import {
  parseOnboarding,
  saveDeploymentOnboarding,
  saveOnboardingScope,
  type StartScope,
  type StartStep,
} from "@/lib/onboarding-api";
import { qk } from "@/lib/query-keys";

interface StepReport {
  step: StartStep;
  userId: string;
  organizationId: string | null;
  scope?: StartScope;
}

function ownsReport(report: StepReport): boolean {
  return (
    useAuthStore.getState().user?.id === report.userId &&
    useOrgStore.getState().activeOrgId === report.organizationId
  );
}

/** Serialize reported positions across mounted steps; progress never proves completion. */
export function useReportStartStep(
  step: StartStep,
  organizationId: string | null,
  enabled = true,
  scope?: StartScope,
) {
  const userId = useAuthStore((state) => state.user?.id);
  const activeOrganizationId = useOrgStore((state) => state.activeOrgId);
  const current = useRef({ step, enabled, scope, mounted: false });
  useEffect(() => {
    const context = current.current;
    context.step = step;
    context.enabled = enabled;
    context.scope = scope;
    context.mounted = true;
    return () => {
      context.mounted = false;
    };
  }, [step, enabled, scope]);
  const errors = useTranslations("errors");
  const common = useTranslations("common");
  const { mutate } = useMutation({
    // Identity changes must detach the observer from the previous account's queue.
    mutationKey: [
      ...qk.onboarding.state(userId ?? "", organizationId ?? ""),
      "progress",
      scope ?? "personal",
    ],
    scope: { id: `onboarding-progress:${userId}:${organizationId}:${scope ?? "personal"}` },
    mutationFn: async (report: StepReport) => {
      if (!ownsReport(report)) throw new Error(errors("sessionExpired"));
      if (report.scope === "deployment" && report.organizationId === null)
        return saveDeploymentOnboarding({ current_step: report.step });
      if (report.organizationId === null) throw new Error(errors("sessionExpired"));
      if (report.scope)
        return saveOnboardingScope(
          report.scope,
          { current_step: report.step },
          report.organizationId,
        );
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
        current.current.step !== report.step ||
        current.current.scope !== report.scope
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
              current.current.scope === report.scope &&
              ownsReport(report)
            )
              mutate(report);
          },
        },
      });
    },
  });
  useEffect(() => {
    if (
      enabled &&
      userId &&
      (organizationId !== null || scope === "deployment") &&
      organizationId === activeOrganizationId
    )
      mutate({ step, userId, organizationId, scope });
  }, [step, organizationId, activeOrganizationId, userId, enabled, scope, mutate]);
}
