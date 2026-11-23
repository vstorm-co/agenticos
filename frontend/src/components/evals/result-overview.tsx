"use client";

import { useTranslations } from "next-intl";
import type { EvalComparison, EvalRunArm } from "@/types/eval-runs";

/** The result in task language; the measurement and execution records remain in Details. */
export function ResultOverview({
  comparison,
  candidate,
}: {
  comparison: EvalComparison;
  candidate: EvalRunArm;
}) {
  const t = useTranslations("evals.plain");
  const summary = comparison.candidate_summary;
  const undecided = summary.incomplete + summary.ungraded;
  const invalid = comparison.verdict === "invalid";
  const paired = comparison.baseline !== null;
  const families = comparison.families?.filter((family) => family.better).length ?? 0;
  const title =
    paired && comparison.verdict === null
      ? "notCompared"
      : invalid
        ? "invalid"
        : comparison.verdict === "worse" ||
            comparison.verdict === "mixed" ||
            comparison.overall === "worse"
          ? "worse"
          : undecided > 0
            ? "incomplete"
            : !paired
              ? "single"
              : comparison.fixed_confirmed > 0
                ? "improved"
                : families > 0
                  ? "requirements"
                  : "unchanged";
  return (
    <section className="space-y-2" aria-label={t("label")}>
      <h2 className="text-lg font-medium">
        {t(title, { passed: summary.passed, cases: summary.cases })}
      </h2>
      <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
        {paired && comparison.verdict === null
          ? t("notCompared")
          : invalid
            ? t(comparison.invalid_reason_code === "too_few_held_out" ? "tooFew" : "cannotCompare")
            : undecided > 0
              ? t("partial")
              : comparison.overall === "worse" && comparison.regressions_confirmed === 0
                ? t("overallWorseBody")
                : families > 0 && comparison.fixed_confirmed === 0
                  ? t("requirementsBody")
                  : paired
                    ? t("changes", {
                        fixed: comparison.fixed_confirmed,
                        broken: comparison.regressions_confirmed,
                      })
                    : t("singleBody", { failed: candidate.summary.failed })}
      </p>
      {undecided > 0 && (
        <p className="text-warning-ink text-sm">{t("undecided", { count: undecided })}</p>
      )}
      {!invalid && comparison.fixed_unconfirmed + comparison.regressions_unconfirmed > 0 && (
        <p className="text-muted-foreground text-sm">{t("unstable")}</p>
      )}
    </section>
  );
}
