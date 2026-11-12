"use client";

import { Spinner } from "@/components/ui/spinner";
import { useTranslations } from "next-intl";

import { usePermissions } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import type { Period } from "@/lib/dashboard/period";
import { Perm } from "@/types/permissions";
import { StartChecklist } from "./start-checklist";
import { SuggestionsWidget } from "./widgets/suggestions";

/**
 * What opens the person's own dashboard (#2301): what to do next and what waits
 * for them, side by side - Get started on the left, the Briefing on the right.
 * Once the checklist is done or closed it renders nothing, and the Briefing
 * takes the whole row.
 */
export function MeOpening({
  orgId,
  period,
  pending = false,
}: {
  orgId: string | null;
  period: Period;
  pending?: boolean;
}) {
  const t = useTranslations("dashboard.widgets.suggestions");
  const states = useTranslations("dashboard.states");
  const { can } = usePermissions();
  if (pending)
    return (
      <div
        role="status"
        aria-busy="true"
        aria-label={states("loading")}
        className="bg-card mt-6 flex h-56 items-center justify-center rounded-2xl border"
      >
        <Spinner className="text-muted-foreground size-5" aria-hidden />
      </div>
    );
  return (
    // Match the checklist while it is visible; a briefing on its own should not
    // keep the space of a checklist that has been completed or dismissed.
    <div className="mt-6 flex flex-col gap-6 lg:flex-row [&>*]:min-w-0 [&>*]:shrink-0 lg:[&>*]:flex-1 [&>.dash-widget]:h-56 [&>.dash-widget]:min-h-56 lg:[&>.dash-widget:not(:only-child)]:h-[31rem]">
      {orgId && <StartChecklist orgId={orgId} className="mt-0" />}
      {can(Perm.agentsRun) && (
        <SuggestionsWidget
          title={t("title")}
          hint={t("description")}
          period={period}
          seeAll={ROUTES.INBOX}
        />
      )}
    </div>
  );
}
