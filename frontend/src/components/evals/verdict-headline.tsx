"use client";

import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import type { CaseFlip, EvalComparison, EvalRun, EvalRunArm, Verdict } from "@/types/eval-runs";
import { percent } from "./format";
import { sideName } from "./names";

export const VERDICT_TONE: Record<Verdict, "success" | "destructive" | "secondary" | "warning"> = {
  better: "success",
  worse: "destructive",
  mixed: "warning",
  no_difference: "secondary",
  invalid: "warning",
};

/**
 * When a run with no change that held still says something moved: this many
 * unconfirmed changes, or a pass rate this far apart. Past either, the model
 * is more likely unsteady than the two sides alike.
 */
const UNSTEADY_CHANGES = 3;
const UNSTEADY_GAP = 0.2;

/** How long a quoted question may run in a sentence before it is cut. */
const QUOTED = 120;

export function quoted(text: string): string {
  return text.length <= QUOTED ? text : `${text.slice(0, QUOTED - 1).trimEnd()}…`;
}

/** The first confirmed flip of a kind, and how many of the candidate's tries repeated it. */
function example(comparison: EvalComparison, flip: "regression" | "fixed") {
  const found = comparison.cases.find((c: CaseFlip) => c.flip === flip && c.confirmed);
  if (found === undefined) return null;
  const tries = [found.candidate, ...found.candidate_reruns];
  return {
    question: quoted(found.input),
    held: tries.filter((outcome) => outcome === found.candidate).length,
    tries: tries.length,
  };
}

/** The candidate's cases neither passed nor failed, whatever kept them undecided. */
export function undecidedOf(arm: EvalRunArm): number {
  return arm.summary.incomplete + arm.summary.ungraded;
}

/**
 * The verdict as a badge, toned by what the confirmed flips say, and beside it -
 * muted, a qualifier and never in its place - which way it moved overall. A
 * case left undecided makes anything short of a confirmed break inconclusive.
 */
export function VerdictBadge({
  comparison,
  undecided,
}: {
  comparison: EvalComparison;
  undecided: number;
}) {
  const t = useTranslations("evals.comparison");
  const { verdict, overall } = comparison;
  const broke = verdict === "worse" || verdict === "mixed" || verdict === "invalid";
  if (undecided > 0 && !broke) {
    return <Badge variant="warning">{t("verdict.inconclusive")}</Badge>;
  }
  if (verdict === null) return null;
  return (
    <span className="flex flex-wrap items-center gap-2">
      <Badge variant={VERDICT_TONE[verdict]}>{t(`verdict.${verdict}`)}</Badge>
      {overall !== null && <Badge variant="outline">{t(`overall.${overall}`)}</Badge>}
    </span>
  );
}

/**
 * The verdict as sentences a person reads first: which cases broke or were
 * fixed every time they were asked, one of them quoted, then whether the
 * candidate is better or worse as a whole, then the pass rates - each case as
 * it settled, the first answers alone on hover.
 */
export function VerdictHeadline({
  run,
  candidate,
  comparison,
}: {
  run: EvalRun;
  candidate: EvalRunArm;
  comparison: EvalComparison;
}) {
  const t = useTranslations("evals.headline");
  const tSide = useTranslations("evals");
  const locale = useLocale();
  const { baseline, verdict, overall } = comparison;
  const to = percent(comparison.candidate_summary.pass_rate, locale);
  const { incomplete, ungraded, cases } = candidate.summary;
  const counted = { undecided: incomplete + ungraded, cases };
  const values = {
    candidate: sideName(candidate, tSide, run.proposal_check),
    dataset: run.dataset_name,
  };
  const why = counted.undecided > 0 && (
    <span className="text-muted-foreground block text-sm font-normal">
      {t("undecidedWhy", { ungraded, incomplete, both: String(ungraded > 0 && incomplete > 0) })}
    </span>
  );
  if (baseline === null || verdict === null) {
    return (
      <>
        <span className="block">{t("first", { ...values, ...counted, rate: to })}</span>
        {why}
      </>
    );
  }
  const broke = comparison.regressions_confirmed;
  const fixed = comparison.fixed_confirmed;
  const shown = example(comparison, verdict === "better" ? "fixed" : "regression");
  const sentence = {
    ...values,
    baseline: sideName(baseline, tSide),
    broke,
    fixed,
    others: (verdict === "better" ? fixed : broke) - 1,
    question: shown?.question ?? "",
    held: shown?.held ?? 0,
    tries: shown?.tries ?? 0,
    changes: comparison.regressions_unconfirmed + comparison.fixed_unconfirmed,
  };
  const gap = Math.abs(
    (comparison.candidate_summary.pass_rate ?? 0) - (comparison.baseline_summary?.pass_rate ?? 0),
  );
  const unsteady =
    verdict === "no_difference" && (sentence.changes >= UNSTEADY_CHANGES || gap >= UNSTEADY_GAP);
  const firstTo = percent(comparison.candidate_summary.first_pass_rate, locale);
  const firstFrom = percent(comparison.baseline_summary?.first_pass_rate ?? null, locale);
  return (
    <>
      <span className="block">{t(verdict, sentence)}</span>
      {unsteady && (
        <span className="text-muted-foreground block text-sm font-normal">{t("unsteady")}</span>
      )}
      {overall !== null && <span className="block">{t("overall", { ...sentence, overall })}</span>}
      {verdict !== "invalid" && (
        <span
          className="text-muted-foreground block text-sm font-normal"
          title={t("firstPassRate", { from: firstFrom, to: firstTo })}
        >
          {t("passRate", {
            from: percent(comparison.baseline_summary?.pass_rate ?? null, locale),
            to,
            ...counted,
          })}
        </span>
      )}
      {why}
    </>
  );
}
