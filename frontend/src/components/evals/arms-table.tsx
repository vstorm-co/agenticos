"use client";

import { useLocale, useTranslations } from "next-intl";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import type { EvalRunArm } from "@/types/eval-runs";
import { percent, seconds, usd } from "./format";

/**
 * Every arm of a run side by side - the model comparison when the candidate ran
 * on several, and the baseline beside it when one ran here.
 */
export function ArmsTable({ arms }: { arms: EvalRunArm[] }) {
  const t = useTranslations("evals.arms");
  const locale = useLocale();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-muted-foreground text-left text-xs">
            <tr>
              <th className="py-1 pr-3 font-normal">{t("arm")}</th>
              <th className="py-1 pr-3 font-normal">{t("passRate")}</th>
              <th className="py-1 pr-3 font-normal">{t("undecided")}</th>
              <th className="py-1 pr-3 font-normal">{t("costPerPass")}</th>
              <th className="py-1 pr-3 font-normal">{t("tokens")}</th>
              <th className="py-1 pr-3 font-normal">{t("latency")}</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {arms.map((arm) => (
              <tr key={arm.id} className="border-t">
                <td className="py-2 pr-3">
                  {t(`role.${arm.role}`, { model: arm.model_label })}
                  {arm.reused_from_arm_id && (
                    <span className="text-muted-foreground"> · {t("reused")}</span>
                  )}
                </td>
                <td className="py-2 pr-3">{percent(arm.summary.pass_rate, locale)}</td>
                <td className="py-2 pr-3">{arm.summary.incomplete}</td>
                <td className="py-2 pr-3">{usd(arm.summary.cost_per_pass_usd, locale)}</td>
                <td className="py-2 pr-3">
                  {arm.summary.avg_tokens === null ? "—" : Math.round(arm.summary.avg_tokens)}
                </td>
                <td className="py-2 pr-3">
                  {t("p50p95", {
                    p50: seconds(arm.summary.p50_ms, locale),
                    p95: seconds(arm.summary.p95_ms, locale),
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
