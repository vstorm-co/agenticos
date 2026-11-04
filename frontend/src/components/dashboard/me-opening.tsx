"use client";

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
export function MeOpening({ orgId, period }: { orgId: string | null; period: Period }) {
  const t = useTranslations("dashboard.widgets.suggestions");
  const { can } = usePermissions();
  return (
    // Reserve the checklist before its queries settle. Only the briefing stretches
    // beside it; overriding every child's height erased the checklist's slot.
    <div className="mt-6 flex flex-col gap-6 lg:flex-row [&>*]:min-w-0 [&>*]:shrink-0 lg:[&>*]:flex-1 [&>.dash-widget]:h-56 [&>.dash-widget]:min-h-56 lg:[&>.dash-widget]:h-[31rem]">
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
