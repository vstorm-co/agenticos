"use client";

import { useTranslations } from "next-intl";
import type { ImprovementMeasurement as Measurement } from "@/types/eval-runs";

/** A proposal is learned on train cases and judged on a frozen, separate holdout. */
export function ImprovementMeasurement({ measurement }: { measurement: Measurement }) {
  const t = useTranslations("evals.improvementSplit");
  const missing = Math.max(0, measurement.minimum_holdout - measurement.gradable_holdout);
  return (
    <section aria-label={t("title")} className="space-y-2 rounded-lg border p-4">
      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-muted-foreground">{t("train")}</dt>
          <dd className="font-medium tabular-nums">{measurement.train_case_ids.length}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("holdout")}</dt>
          <dd className="font-medium tabular-nums">{measurement.holdout_case_ids.length}</dd>
        </div>
      </dl>
      <p className="text-muted-foreground text-xs">{t("body")}</p>
      {measurement.excluded_case_ids.length > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("excluded", { count: measurement.excluded_case_ids.length })}
        </p>
      )}
      {missing > 0 && (
        <p role="status" className="text-warning text-sm">
          {t("needed", { count: missing })}
        </p>
      )}
    </section>
  );
}
