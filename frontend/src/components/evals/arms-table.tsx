"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import type {
  ArmSummary,
  ComparisonSide,
  EvalRunArm,
  ProposalCheckRecord,
} from "@/types/eval-runs";
import { percent, seconds, usd } from "./format";
import { sideName } from "./names";

function SideLabel({
  agentId,
  arm,
  baseline,
  check,
}: {
  agentId: string;
  arm: EvalRunArm;
  baseline: ComparisonSide | null;
  check: ProposalCheckRecord | null | undefined;
}) {
  const t = useTranslations("evals");
  const locale = useLocale();
  const name = t("sideModel", { name: sideName(arm, t, check), model: arm.model_label });
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

/** One side's numbers, a dash where it has none under the tag read. */
function SummaryCell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <td className="flex min-w-0 items-start justify-between gap-4 py-1.5 md:table-cell md:py-2 md:pr-3">
      <span className="text-muted-foreground text-xs md:hidden">{label}</span>
      <span className="min-w-0 text-right break-words md:text-left">{children}</span>
    </td>
  );
}

function SummaryCells({ summary, live }: { summary: ArmSummary | undefined; live: boolean }) {
  const t = useTranslations("evals.arms");
  const locale = useLocale();
  return (
    <>
      <SummaryCell label={t("passRate")}>{percent(summary?.pass_rate ?? null, locale)}</SummaryCell>
      <SummaryCell label={live ? t("pending") : t("undecided")}>
        {summary === undefined ? "—" : summary.incomplete + summary.ungraded}
      </SummaryCell>
      <SummaryCell label={t("costPerPass")}>
        {usd(summary?.cost_per_pass_usd ?? null, locale)}
      </SummaryCell>
      <SummaryCell label={t("tokens")}>
        {summary === undefined || summary.avg_tokens === null
          ? "—"
          : Math.round(summary.avg_tokens)}
      </SummaryCell>
      <SummaryCell label={t("latency")}>
        {t("p50p95", {
          p50: seconds(summary?.p50_ms ?? null, locale),
          p95: seconds(summary?.p95_ms ?? null, locale),
        })}
      </SummaryCell>
    </>
  );
}

/**
 * Every side of a run next to each other - the draft beside what is live, or
 * each model the candidate ran on - over every case, or over the cases
 * carrying `tag`. A run that measured itself against an earlier run without
 * keeping it as a side of its own still shows that run's numbers, from the
 * comparison.
 */
export function ArmsTable({
  agentId,
  arms,
  tag,
  live,
  baseline,
  check,
  baselineSummary,
}: {
  agentId: string;
  arms: EvalRunArm[];
  tag: string | null;
  /** Whether the run still answers, so an empty result is pending rather than undecided. */
  live: boolean;
  /** The side the candidate is compared with, to name the run a reused result came from. */
  baseline: ComparisonSide | null;
  /** What a check of a proposal measured, to name its candidate by what it adds. */
  check?: ProposalCheckRecord | null;
  /** That side's numbers over the cases both answered, as the comparison read them. */
  baselineSummary: ArmSummary | null;
}) {
  const t = useTranslations("evals.arms");
  const tSide = useTranslations("evals");
  const locale = useLocale();
  const earlier =
    baseline !== null && baselineSummary !== null && !arms.some((arm) => arm.role === "baseline")
      ? baseline
      : null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{tag === null ? t("title") : t("titleTag", { tag })}</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0 overflow-x-auto">
        <table className="block w-full text-sm md:table">
          <thead className="text-muted-foreground hidden text-left text-xs md:table-header-group">
            <tr>
              <th className="py-1 pr-3 font-normal">{t("side")}</th>
              <th className="py-1 pr-3 font-normal">{t("passRate")}</th>
              <th className="py-1 pr-3 font-normal">{live ? t("pending") : t("undecided")}</th>
              <th className="py-1 pr-3 font-normal">{t("costPerPass")}</th>
              <th className="py-1 pr-3 font-normal">{t("tokens")}</th>
              <th className="py-1 pr-3 font-normal">{t("latency")}</th>
            </tr>
          </thead>
          <tbody className="block tabular-nums md:table-row-group">
            {arms.map((arm) => (
              <tr
                key={arm.id}
                className="block border-b py-3 last:border-b-0 md:table-row md:border-t md:border-b-0 md:py-0"
              >
                <td className="block py-2 font-medium break-words md:table-cell md:pr-3 md:font-normal">
                  <SideLabel agentId={agentId} arm={arm} baseline={baseline} check={check} />
                </td>
                {/* An arm with no case under the tag has no entry for it. */}
                <SummaryCells summary={tag === null ? arm.summary : arm.by_tag[tag]} live={live} />
              </tr>
            ))}
            {earlier !== null && (
              <tr className="block border-b py-3 last:border-b-0 md:table-row md:border-t md:border-b-0 md:py-0">
                <td className="block py-2 font-medium break-words md:table-cell md:pr-3 md:font-normal">
                  {tSide("sideModel", {
                    name: sideName(earlier, tSide),
                    model: earlier.model_label,
                  })}
                  {" · "}
                  <Link
                    href={`${ROUTES.AGENTS}/${agentId}/evals/${earlier.run_id}`}
                    className="text-muted-foreground underline underline-offset-4"
                  >
                    {earlier.finished_at
                      ? tSide("arms.reusedFrom", {
                          date: formatDateTime(earlier.finished_at, locale),
                        })
                      : tSide("arms.reused")}
                  </Link>
                </td>
                <SummaryCells
                  summary={tag === null ? (baselineSummary ?? undefined) : undefined}
                  live={live}
                />
              </tr>
            )}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
