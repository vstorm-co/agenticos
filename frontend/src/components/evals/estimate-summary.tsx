"use client";

import { useLocale, useTranslations } from "next-intl";

import type { EvalRunEstimate } from "@/types/eval-runs";
import { usd } from "./format";

/**
 * What a run is expected to cost, and what each budget keeps for live traffic
 * once it has spent it - the number a person consents to before anything runs.
 */
export function EstimateSummary({ estimate }: { estimate: EvalRunEstimate }) {
  const t = useTranslations("evals.estimate");
  const locale = useLocale();
  return (
    <div className="bg-muted/40 space-y-3 rounded-lg border p-4 text-sm">
      <ul className="space-y-1">
        {estimate.arms.map((arm, index) => (
          <li key={index} className="flex items-center justify-between gap-3">
            <span className="text-muted-foreground">
              {t(`arm.${arm.role}`, { model: arm.model_label, version: arm.version_number ?? 0 })}
              {arm.basis !== "history" && ` · ${t(`basis.${arm.basis}`)}`}
            </span>
            <span className="tabular-nums">{usd(arm.cost_usd, locale)}</span>
          </li>
        ))}
        {Number(estimate.judge_usd) > 0 && (
          <li className="flex items-center justify-between gap-3">
            <span className="text-muted-foreground">{t("judge")}</span>
            <span className="tabular-nums">{usd(estimate.judge_usd, locale)}</span>
          </li>
        )}
      </ul>
      <p className="flex items-center justify-between gap-3 font-medium">
        <span>{t("total", { count: estimate.cases })}</span>
        <span className="tabular-nums">{usd(estimate.total_usd, locale)}</span>
      </p>
      <p className="text-muted-foreground text-xs">
        {t("reruns", { amount: usd(estimate.rerun_ceiling_usd, locale) })}
      </p>
      <p className="text-xs">
        {t.rich("after", {
          agent:
            estimate.agent_after_usd === null ? t("noCap") : usd(estimate.agent_after_usd, locale),
          org: estimate.org_after_usd === null ? t("noCap") : usd(estimate.org_after_usd, locale),
          b: (chunk) => <strong>{chunk}</strong>,
        })}
      </p>
      {!estimate.affordable && <p className="text-destructive text-xs">{t("unaffordable")}</p>}
    </div>
  );
}
