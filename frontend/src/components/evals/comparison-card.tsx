"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import type { CaseFlip, ComparisonSide, EvalComparison, Flip, Trend } from "@/types/eval-runs";
import { sideName } from "./names";

const TREND_TONE: Record<Trend, "success" | "destructive" | "secondary" | "outline"> = {
  better: "success",
  worse: "destructive",
  unchanged: "secondary",
  unknown: "outline",
};

function Side({ side, agentId }: { side: ComparisonSide; agentId: string }) {
  const t = useTranslations("evals");
  const locale = useLocale();
  return (
    <Link
      href={`${ROUTES.AGENTS}/${agentId}/evals/${side.run_id}`}
      className="hover:bg-accent/40 block rounded-md px-2 py-1 text-sm"
    >
      {t("comparison.side", {
        candidate: sideName(side, t),
        model: side.model_label,
        dataset: side.dataset_version,
        date: side.finished_at
          ? formatDateTime(side.finished_at, locale)
          : t("comparison.unfinished"),
      })}
    </Link>
  );
}

function counted(cases: CaseFlip[], flip: Flip, confirmed: boolean) {
  return cases.filter((item) => item.flip === flip && item.confirmed === confirmed).length;
}

/**
 * How the verdict was reached: the two sides, the cases that changed - held on
 * every rerun apart from those that did not - and efficiency beside it. With a
 * `tag` the changes are that tag's cases; the verdict is still over every case.
 */
export function ComparisonCard({
  agentId,
  comparison,
  tag,
}: {
  agentId: string;
  comparison: EvalComparison;
  tag: string | null;
}) {
  const t = useTranslations("evals.comparison");
  const { baseline, efficiency } = comparison;
  if (baseline === null) return null;
  const scope =
    tag === null
      ? null
      : { tag, cases: comparison.cases.filter((item) => item.tags.includes(tag)) };
  const flips =
    scope === null
      ? ([
          ["regressionsConfirmed", comparison.regressions_confirmed],
          ["regressionsUnconfirmed", comparison.regressions_unconfirmed],
          ["fixedConfirmed", comparison.fixed_confirmed],
          ["fixedUnconfirmed", comparison.fixed_unconfirmed],
        ] as const)
      : ([
          ["regressionsConfirmed", counted(scope.cases, "regression", true)],
          ["regressionsUnconfirmed", counted(scope.cases, "regression", false)],
          ["fixedConfirmed", counted(scope.cases, "fixed", true)],
          ["fixedUnconfirmed", counted(scope.cases, "fixed", false)],
        ] as const);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="grid gap-2 sm:grid-cols-2">
          <div>
            <p className="text-muted-foreground text-xs">{t("candidate")}</p>
            <Side side={comparison.candidate} agentId={agentId} />
          </div>
          <div>
            <p className="text-muted-foreground text-xs">
              {comparison.paired ? t("baselinePaired") : t("baselinePast")}
            </p>
            <Side side={baseline} agentId={agentId} />
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {flips.map(([key, count]) => (
            <div
              key={key}
              className="rounded-md border px-3 py-2"
              title={key.endsWith("Unconfirmed") ? t("unconfirmedHint") : t("confirmedHint")}
            >
              <dt className="text-muted-foreground text-xs">{t(key)}</dt>
              <dd className="text-lg font-semibold tabular-nums">{count}</dd>
            </div>
          ))}
        </dl>
        <p className="text-muted-foreground text-xs">
          {scope === null
            ? t("compared", { compared: comparison.compared, skipped: comparison.not_compared })
            : t("comparedTag", { compared: scope.cases.length, tag: scope.tag })}
        </p>
        <p className="text-muted-foreground text-xs">{t("glossary")}</p>
        {efficiency && (
          <div className="flex flex-wrap gap-2">
            {(Object.keys(efficiency) as (keyof typeof efficiency)[]).map((metric) => (
              <Badge key={metric} variant={TREND_TONE[efficiency[metric]]}>
                {t(`metric.${metric}`)}: {t(`trend.${efficiency[metric]}`)}
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
