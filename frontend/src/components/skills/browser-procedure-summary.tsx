"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui";
import type { BrowserProcedure } from "@/types/browser-teaching";

/** Provenance belongs to this proposed/applied version; it does not authorize replay. */
export function BrowserProcedureSummary({ procedure }: { procedure: BrowserProcedure }) {
  const t = useTranslations("browserTeaching");
  return (
    <section className="space-y-2 rounded-lg border p-3" aria-label={t("procedureTitle")}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{t("procedureTitle")}</Badge>
        <span className="text-sm">{t("capturedSteps", { count: procedure.steps.length })}</span>
      </div>
      <p className="text-muted-foreground text-xs break-words">{procedure.origins.join(", ")}</p>
      <p className="text-muted-foreground text-sm">
        {procedure.source === "manual"
          ? t("manualEvidence")
          : procedure.verified_success
            ? t("completedEvidence")
            : t("completionPending")}
      </p>
      <p className="text-muted-foreground text-xs">{t("versionAuthority")}</p>
    </section>
  );
}
