"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import type { ArmSummary, ComparisonSide, EvalRunArm } from "@/types/eval-runs";
import { percent, seconds, usd } from "./format";
import { sideName } from "./names";

function SideLabel({
  agentId,
  arm,
  baseline,
}: {
  agentId: string;
  arm: EvalRunArm;
  baseline: ComparisonSide | null;
}) {
  const t = useTranslations("evals");
  const locale = useLocale();
  const name = t("sideModel", { name: sideName(arm, t), model: arm.model_label });
  // A reused side answered nothing here: it is an earlier run's result, and
  // says which.
  if (arm.reused_from_arm_id === null || baseline === null) return <>{name}</>;
  return (
    <>
      {name}
      {" · "}
      <Link
        href={`${ROUTES.AGENTS}/${agentId}/evals/${baseline.run_id}`}
        className="text-muted-foreground underline underline-offset-4"
      >
        {baseline.finished_at
          ? t("arms.reusedFrom", { date: formatDateTime(baseline.finished_at, locale) })
          : t("arms.reused")}
      </Link>
    </>
  );
}

/**
 * Every side of a run next to each other - the draft beside what is live, or
 * each model the candidate ran on - over every case, or over the cases
 * carrying `tag`.
 */
export function ArmsTable({
  agentId,
  arms,
  tag,
  live,
  baseline,
}: {
  agentId: string;
  arms: EvalRunArm[];
  tag: string | null;
  /** Whether the run still answers, so an empty result is pending rather than undecided. */
  live: boolean;
  /** The side the candidate is compared with, to name the run a reused result came from. */
  baseline: ComparisonSide | null;
}) {
  const t = useTranslations("evals.arms");
  const locale = useLocale();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{tag === null ? t("title") : t("titleTag", { tag })}</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-muted-foreground text-left text-xs">
            <tr>
              <th className="py-1 pr-3 font-normal">{t("side")}</th>
              <th className="py-1 pr-3 font-normal">{t("passRate")}</th>
              <th className="py-1 pr-3 font-normal">{live ? t("pending") : t("undecided")}</th>
              <th className="py-1 pr-3 font-normal">{t("costPerPass")}</th>
              <th className="py-1 pr-3 font-normal">{t("tokens")}</th>
              <th className="py-1 pr-3 font-normal">{t("latency")}</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {arms.map((arm) => {
              // An arm with no case under the tag has no entry for it.
              const summary: ArmSummary | undefined = tag === null ? arm.summary : arm.by_tag[tag];
              return (
                <tr key={arm.id} className="border-t">
                  <td className="py-2 pr-3">
                    <SideLabel agentId={agentId} arm={arm} baseline={baseline} />
                  </td>
                  <td className="py-2 pr-3">{percent(summary?.pass_rate ?? null, locale)}</td>
                  <td className="py-2 pr-3">{summary?.incomplete ?? "—"}</td>
                  <td className="py-2 pr-3">{usd(summary?.cost_per_pass_usd ?? null, locale)}</td>
                  <td className="py-2 pr-3">
                    {summary === undefined || summary.avg_tokens === null
                      ? "—"
                      : Math.round(summary.avg_tokens)}
                  </td>
                  <td className="py-2 pr-3">
                    {t("p50p95", {
                      p50: seconds(summary?.p50_ms ?? null, locale),
                      p95: seconds(summary?.p95_ms ?? null, locale),
                    })}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
