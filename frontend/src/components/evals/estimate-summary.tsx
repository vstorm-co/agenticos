"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { ROUTES } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import type { ArmEstimate, EvalRunEstimate } from "@/types/eval-runs";
import type { DatasetScoring } from "@/types/scoring";
import { usd } from "./format";

/** What grades a dataset's answers, by name, in the order the scorers run. */
export function graders(
  scoring: DatasetScoring,
  judge: string,
  t: (key: string, values?: { criteria?: string; name?: string }) => string,
  locale: string,
): string {
  const list = new Intl.ListFormat(locale, { type: "conjunction" });
  const parts: string[] = [];
  if (scoring.checks.enabled) parts.push(t("grader.checks"));
  if (scoring.trajectory.enabled) parts.push(t("grader.trajectory"));
  if (scoring.reference.enabled) parts.push(t("grader.reference"));
  if (scoring.judge.enabled) {
    const criteria = scoring.judge.criteria.map((criterion) => criterion.name);
    parts.push(
      criteria.length === 0
        ? t("grader.judge", { name: judge })
        : t("grader.judgeRubric", { name: judge, criteria: list.format(criteria) }),
    );
  }
  return list.format(parts);
}

function ArmLine({ arm, agentId }: { arm: ArmEstimate; agentId: string }) {
  const t = useTranslations("evals.estimate");
  const locale = useLocale();
  const tEvals = useTranslations("evals");
  const name =
    arm.version_number === null
      ? tEvals("draft")
      : tEvals("version", { version: arm.version_number });
  return (
    <span className="text-muted-foreground">
      {t("side", { name, model: arm.model_label })}
      {arm.basis === "fallback" && ` · ${t("basis.fallback")}`}
      {arm.basis === "cached" && arm.cached_from_run_id !== null && (
        <>
          {" · "}
          <Link
            href={`${ROUTES.AGENTS}/${agentId}/evals/${arm.cached_from_run_id}`}
            className="underline underline-offset-4"
          >
            {arm.cached_at
              ? t("basis.cachedAt", { date: formatDateTime(arm.cached_at, locale) })
              : t("basis.cached")}
          </Link>
        </>
      )}
    </span>
  );
}

/**
 * What a run is expected to cost, what grades it, and what each budget keeps
 * for live traffic once it has spent it - the number a person consents to
 * before anything runs.
 */
export function EstimateSummary({
  agentId,
  estimate,
  scoring,
  judgeName,
}: {
  agentId: string;
  estimate: EvalRunEstimate;
  /** The dataset's scoring, when it is known, to say what grades the answers. */
  scoring: DatasetScoring | null;
  /** The judge the dataset names, or null to call it the default one. */
  judgeName: string | null;
}) {
  const t = useTranslations("evals.estimate");
  const locale = useLocale();
  const judge = judgeName ?? t("judge");
  // A judge grading on the model it grades favours answers like its own.
  const judgedOwnModel = estimate.arms.find(
    (arm) =>
      estimate.judge_model_profile_id !== null &&
      arm.model_profile_id === estimate.judge_model_profile_id,
  );
  return (
    <div className="bg-muted/40 space-y-3 rounded-lg border p-4 text-sm">
      <ul className="space-y-1">
        {estimate.arms.map((arm, index) => (
          <li key={index} className="flex items-center justify-between gap-3">
            <ArmLine arm={arm} agentId={agentId} />
            <span className="tabular-nums">{usd(arm.cost_usd, locale)}</span>
          </li>
        ))}
        {Number(estimate.judge_usd) > 0 && (
          <li className="flex items-center justify-between gap-3">
            <span className="text-muted-foreground">{judge}</span>
            <span className="tabular-nums">{usd(estimate.judge_usd, locale)}</span>
          </li>
        )}
      </ul>
      <p className="flex items-center justify-between gap-3 font-medium">
        <span>{t("total", { count: estimate.cases })}</span>
        <span className="tabular-nums">{usd(estimate.total_usd, locale)}</span>
      </p>
      {scoring && (
        <p className="text-muted-foreground text-xs">
          {t("gradedBy", { graders: graders(scoring, judge, t, locale) })}
        </p>
      )}
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
      {judgedOwnModel && (
        <p className="text-warning text-xs">
          {t("judgeSameModel", { model: judgedOwnModel.model_label })}
        </p>
      )}
      {!estimate.affordable && <p className="text-destructive text-xs">{t("unaffordable")}</p>}
    </div>
  );
}
