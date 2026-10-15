"use client";

import dynamic from "next/dynamic";
import { useLocale, useTranslations } from "next-intl";

import type { PassRateLine } from "@/components/charts/pass-rate-lines.impl";
import { CHART_MIN_HEIGHT } from "@/lib/dashboard/system";
import { cn } from "@/lib/utils";
import type { EvalRun } from "@/types/eval-runs";
import { percent } from "./format";
import { sideName } from "./names";

const PassRateLinesImpl = dynamic(
  () => import("@/components/charts/pass-rate-lines.impl").then((m) => m.PassRateLinesImpl),
  {
    ssr: false,
    loading: () => <div className="bg-muted h-full w-full animate-pulse rounded-md" />,
  },
);

const SERIES = ["--series-1", "--series-2", "--series-3", "--series-4", "--series-5"];

type Translate = (key: string, values?: Record<string, string | number>) => string;

/**
 * Finished runs as lines over time, one per group - a dataset on an agent's
 * page, an agent on a dataset's. A point is the candidate's pass rate over
 * every case, a person's decision counted before the scorers', which is the
 * number the run's own page shows.
 */
export function passRateLines(
  runs: EvalRun[],
  group: (run: EvalRun) => { key: string; name: string },
  t: Translate,
  locale: string,
): PassRateLine[] {
  const lines = new Map<string, PassRateLine>();
  const finished = runs
    .filter((run) => run.status === "completed")
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
  for (const run of finished) {
    const arm =
      run.arms.find((item) => item.id === run.outcome?.candidate_arm_id) ??
      run.arms.find((item) => item.role === "candidate");
    if (arm === undefined || arm.summary.pass_rate === null) continue;
    const { key, name } = group(run);
    const line = lines.get(key) ?? {
      key,
      name,
      color: `var(${SERIES[lines.size % SERIES.length]})`,
      points: [],
    };
    lines.set(key, line);
    const label = sideName(arm, t);
    line.points.push({
      at: Date.parse(run.created_at),
      rate: arm.summary.pass_rate,
      label,
      draft: arm.source !== "version",
      detail: t("trend.point", {
        name: label,
        model: arm.model_label,
        rate: percent(arm.summary.pass_rate, locale),
        verdict: run.outcome?.verdict ?? "none",
      }),
    });
  }
  return [...lines.values()];
}

/** The pass-rate trend, with its key and - with one run - what makes it a trend. */
export function PassRateChart({
  lines,
  compact = false,
}: {
  lines: PassRateLine[];
  compact?: boolean;
}) {
  const t = useTranslations("evals");
  const locale = useLocale();
  const points = lines.reduce((sum, line) => sum + line.points.length, 0);
  if (points === 0) return null;
  return (
    <div className="space-y-2" data-tour="evals-trend">
      {lines.length > 1 && (
        <ul className="text-muted-foreground flex flex-wrap items-center gap-3 text-xs">
          {lines.map((line) => (
            <li key={line.key} className="flex items-center gap-1.5">
              <span
                className="size-2.5 shrink-0 rounded-full"
                style={{ background: line.color }}
                aria-hidden
              />
              {line.name}
            </li>
          ))}
        </ul>
      )}
      <div
        role="img"
        aria-label={t("trend.label")}
        className={cn(CHART_MIN_HEIGHT, compact ? "h-32" : "h-48")}
      >
        <PassRateLinesImpl lines={lines} locale={locale} />
      </div>
      <p className="text-muted-foreground text-xs">
        {points === 1 ? t("trend.single") : t("trend.legend")}
      </p>
    </div>
  );
}
