"use client";

import { useLocale, useTranslations } from "next-intl";
import type {
  ImprovementIteration,
  ImprovementVerdict,
  VerdictCriterion,
} from "@/types/improvement";

type Translate = ReturnType<typeof useTranslations>;

/** Still-failing criteria named in a sentence; the table under the attempt lists the rest. */
const NAMED_FAILING = 5;

/** Verdicts that measured a gain: whole questions, or criteria with nothing worse. */
export const GAINS: readonly (ImprovementVerdict | null)[] = ["better", "criteria_better"];

/** The criteria an attempt's verdict kept; none for an attempt measured before they were. */
export function criteriaOf(round: ImprovementIteration | undefined): VerdictCriterion[] {
  const kept = round?.verdict_detail?.criteria;
  return Array.isArray(kept) ? kept : [];
}

export function movedCriteria(round: ImprovementIteration | undefined) {
  const criteria = criteriaOf(round);
  return {
    better: criteria.filter(
      (item) => item.fixed > 0 && item.broken === 0 && item.after >= item.before,
    ),
    worse: criteria.filter((item) => item.broken > 0),
    failing: criteria.filter(
      (item) => item.after < item.graded && item.fixed === 0 && item.broken === 0,
    ),
  };
}

function criterionName(item: VerdictCriterion, criteria: VerdictCriterion[]): string {
  return criteria.filter((other) => other.name === item.name).length > 1
    ? `${item.name} [${item.scorer}]`
    : item.name;
}

function listed(
  t: Translate,
  locale: string,
  items: VerdictCriterion[],
  context: VerdictCriterion[],
  named?: number,
): string {
  const shown = named === undefined ? items : items.slice(0, named);
  const words = shown.map((item) =>
    named === undefined
      ? t("criteria.item", {
          name: criterionName(item, context),
          before: item.before,
          after: item.after,
          graded: item.graded,
        })
      : item.skill
        ? t("criteria.failingSkill", { name: criterionName(item, context), skill: item.skill })
        : criterionName(item, context),
  );
  if (items.length > shown.length)
    words.push(t("criteria.more", { count: items.length - shown.length }));
  return new Intl.ListFormat(locale, { type: "conjunction" }).format(words);
}

/**
 * What an attempt moved criterion by criterion, as sentences: the criteria it made
 * better and the ones still failing when no whole question flipped, and any criterion
 * it made worse, whatever its verdict.
 */
export function criteriaSentences(
  t: Translate,
  locale: string,
  round: ImprovementIteration,
  agent: string,
): string[] {
  const { better, worse, failing } = movedCriteria(round);
  const context = criteriaOf(round);
  const sentences: string[] = [];
  if (round.verdict === "criteria_better" && better.length > 0) {
    sentences.push(
      t("criteria.better", {
        number: round.number,
        agent,
        count: better.length,
        list: listed(t, locale, better, context),
      }),
    );
    if (failing.length > 0)
      sentences.push(
        t("criteria.stillFailing", { list: listed(t, locale, failing, context, NAMED_FAILING) }),
      );
  }
  if (worse.length > 0)
    sentences.push(
      t(round.verdict === "criteria_worse" ? "criteria.worse" : "criteria.worseBeside", {
        number: round.number,
        agent,
        count: worse.length,
        list: listed(t, locale, worse, context),
      }),
    );
  return sentences;
}

/** The criteria sentences for one attempt, as a paragraph; nothing when none moved. */
export function CriteriaNote({ round, agent }: { round: ImprovementIteration; agent: string }) {
  const t = useTranslations("improvement");
  const locale = useLocale();
  const sentences = criteriaSentences(t, locale, round, agent);
  if (sentences.length === 0) return null;
  return <p className="text-sm">{sentences.join(" ")}</p>;
}

function movedText(t: Translate, item: VerdictCriterion): string {
  if (item.fixed > 0 && item.broken > 0)
    return t("movedBoth", { fixed: item.fixed, broken: item.broken });
  if (item.fixed > 0) return t("movedFixed", { count: item.fixed });
  if (item.broken > 0) return t("movedBroken", { count: item.broken });
  return t("movedNone");
}

/** Every criterion a change was measured on: passed before and after, and what moved. */
export function CriteriaTable({ criteria }: { criteria: VerdictCriterion[] }) {
  const t = useTranslations("improvement.criteria");
  if (criteria.length === 0) return null;
  return (
    <section className="space-y-2">
      <h4 className="text-sm font-medium">{t("title")}</h4>
      <table className="w-full text-left text-sm">
        <thead className="text-muted-foreground text-xs">
          <tr>
            <th className="py-1 pr-3 font-normal">{t("criterion")}</th>
            <th className="py-1 pr-3 font-normal">{t("before")}</th>
            <th className="py-1 pr-3 font-normal">{t("after")}</th>
            <th className="py-1 font-normal">{t("moved")}</th>
          </tr>
        </thead>
        <tbody>
          {criteria.map((item) => (
            <tr key={`${item.scorer}:${item.name}`} className="border-t">
              <td className="py-1 pr-3">
                {criterionName(item, criteria)}
                {item.skill && (
                  <span className="text-muted-foreground block text-xs">
                    {t("skill", { skill: item.skill })}
                  </span>
                )}
              </td>
              <td className="py-1 pr-3 tabular-nums">
                {t("passed", { passed: item.before, graded: item.graded })}
              </td>
              <td className="py-1 pr-3 tabular-nums">
                {t("passed", { passed: item.after, graded: item.graded })}
              </td>
              <td className="py-1">{movedText(t, item)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
