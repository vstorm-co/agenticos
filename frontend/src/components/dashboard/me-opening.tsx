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
    // `h-auto` over the widget frame's `h-full`: a fixed height is not stretched,
    // so the Briefing stopped short of the checklist beside it.
    <div className="mt-6 flex flex-col gap-6 lg:flex-row [&>*]:h-auto [&>*]:min-w-0 [&>*]:flex-1">
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
