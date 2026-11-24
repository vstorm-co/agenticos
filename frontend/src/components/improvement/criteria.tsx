"use client";

import { useLocale, useTranslations } from "next-intl";
import type { FamilyMove } from "@/types/eval-runs";
import type {
  ImprovementIteration,
  ImprovementVerdict,
  VerdictCriterion,
  VerdictFamily,
} from "@/types/improvement";

type Translate = ReturnType<typeof useTranslations>;

/** Still-failing criteria named in a sentence; the table under the attempt lists the rest. */
const NAMED_FAILING = 5;

/** Verdicts that measured a gain: whole questions, or criteria with nothing worse. */
export const GAINS: readonly (ImprovementVerdict | null)[] = ["better", "criteria_better"];

/**
 * One row the criteria sentences and table read: a family of criteria, counted question
 * by question, or - for an attempt measured before families - a single criterion.
 */
export interface CriterionRow {
  key: string;
  name: string;
  /** The scorer grading a single criterion; a family has none. */
  scorer?: string;
  graded: number;
  before: number;
  after: number;
  fixed: number;
  broken: number;
  skill?: string | null;
  better: boolean;
  worse: boolean;
}

/** The criteria an attempt's verdict kept; none for an attempt measured before they were. */
export function criteriaOf(round: ImprovementIteration | undefined): VerdictCriterion[] {
  const kept = round?.verdict_detail?.criteria;
  return Array.isArray(kept) ? (kept as VerdictCriterion[]) : [];
}

/** The families an attempt's verdict kept; none for an attempt measured before them. */
export function familiesOf(round: ImprovementIteration | undefined): VerdictFamily[] {
  const kept = round?.verdict_detail?.families;
  return Array.isArray(kept) ? (kept as VerdictFamily[]) : [];
}

/**
 * The longest name a grade keeps for a criterion. A case's own judged check is named
 * by its text cut there and trimmed, so a cut that fell on a space leaves one less.
 */
const NAME_CHARS = 80;

/**
 * A criterion's name as a reader sees it, an ellipsis where its text was cut. At the
 * full length its last word may be cut, so it ends at the word before; one short of
 * it, the cut fell on a space and the last word is whole. A name ending a sentence was
 * written whole.
 */
export function criterionName(name: string): string {
  if (name.length < NAME_CHARS - 1 || /[.!?)]$/.test(name)) return name;
  if (name.length < NAME_CHARS) return `${name}…`;
  const at = name.lastIndexOf(" ");
  return `${(at > 0 ? name.slice(0, at) : name).replace(/[\s,;:.-]+$/, "")}…`;
}

/**
 * Single criteria as rows: better with confirmed fixes, nothing broken and no fewer passes,
 * worse with a break.
 */
export function criterionRows(criteria: VerdictCriterion[]): CriterionRow[] {
  return criteria.map((item) => ({
    key: `${item.scorer}:${item.name}`,
    name: criterionName(item.name),
    scorer: item.scorer,
    graded: item.graded,
    before: item.before,
    after: item.after,
    fixed: item.fixed,
    broken: item.broken,
    skill: item.skill,
    better: item.fixed > 0 && item.broken === 0 && item.after >= item.before,
    worse: item.broken > 0,
  }));
}

/** A comparison's families as rows: the flips that hold, every one when a family is settled. */
export function familyRows(families: FamilyMove[]): CriterionRow[] {
  return families.map((item) => ({
    key: `family:${item.family}`,
    name: criterionName(item.family),
    graded: item.cases,
    before: item.baseline_passed,
    after: item.candidate_passed,
    fixed: item.settled ? item.fixed : item.fixed_confirmed,
    broken: item.settled ? item.broken : item.broken_confirmed,
    better: item.better,
    worse: item.worse,
  }));
}

/** The rows an attempt is read by: its families when it has them, else its criteria. */
export function rowsOf(round: ImprovementIteration | undefined): CriterionRow[] {
  return verdictRows(criteriaOf(round), familiesOf(round));
}

/** A verdict's families as rows, or its single criteria when it kept no families. */
export function verdictRows(
  criteria: VerdictCriterion[],
  families: VerdictFamily[],
): CriterionRow[] {
  if (families.length === 0) return criterionRows(criteria);
  return families.map((item) => ({
    key: `family:${item.family}`,
    name: criterionName(item.family),
    graded: item.cases,
    before: item.before,
    after: item.after,
    fixed: item.fixed,
    broken: item.broken,
    skill: item.skill,
    better: item.better,
    worse: item.worse,
  }));
}

/**
 * What an attempt moved. A row the improver put down to a skill that got worse is not
 * the agent's: it is `skillWorse`, the agent following a faulty skill more closely.
 */
export function movedCriteria(round: ImprovementIteration | undefined) {
  const rows = rowsOf(round);
  return {
    better: rows.filter((item) => item.better),
    worse: rows.filter((item) => item.worse && !item.skill),
    skillWorse: rows.filter((item) => item.worse && !!item.skill),
    failing: rows.filter((item) => item.after < item.graded && !item.better && !item.worse),
  };
}

/**
 * An attempt's criteria taken together: how often they passed before and after over the
 * questions each was graded on, how many got better, and the skills holding back the ones
 * still failing. Null for an attempt measured before criteria were kept.
 */
export function criteriaTotals(round: ImprovementIteration | undefined) {
  const rows = rowsOf(round);
  const graded = rows.reduce((sum, row) => sum + row.graded, 0);
  if (graded === 0) return null;
  const held = rows.filter((row) => row.skill && row.after < row.graded);
  return {
    before: rows.reduce((sum, row) => sum + row.before, 0) / graded,
    after: rows.reduce((sum, row) => sum + row.after, 0) / graded,
    better: rows.filter((row) => row.better).length,
    held: held.length,
    skills: [...new Set(held.map((row) => row.skill as string))],
  };
}

/** A row's name, with its scorer when another criterion shares the name. */
function scoredName(item: CriterionRow, rows: CriterionRow[]): string {
  return item.scorer && rows.filter((other) => other.name === item.name).length > 1
    ? `${item.name} [${item.scorer}]`
    : item.name;
}

function listed(
  t: Translate,
  locale: string,
  items: CriterionRow[],
  context: CriterionRow[],
  named?: number,
): string {
  const shown = named === undefined ? items : items.slice(0, named);
  const words = shown.map((item) =>
    named === undefined
      ? t("criteria.item", {
          name: scoredName(item, context),
          before: item.before,
          after: item.after,
          graded: item.graded,
        })
      : item.skill
        ? t("criteria.failingSkill", { name: scoredName(item, context), skill: item.skill })
        : scoredName(item, context),
  );
  if (items.length > shown.length)
    words.push(t("criteria.more", { count: items.length - shown.length }));
  return new Intl.ListFormat(locale, { type: "conjunction" }).format(words);
}

/**
 * What an attempt moved criterion by criterion, as sentences: the criteria it made
 * better and the ones still failing when no whole question flipped, the criteria it
 * made better beside questions it broke, any criterion it made worse whatever its
 * verdict, and the ones it got worse on by following a skill the improver blamed.
 */
export function criteriaSentences(
  t: Translate,
  locale: string,
  round: ImprovementIteration,
  agent: string,
): string[] {
  const { better, worse, skillWorse, failing } = movedCriteria(round);
  const context = rowsOf(round);
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
  if (round.verdict === "regression" && better.length > 0)
    sentences.push(
      t("criteria.betterBeside", {
        number: round.number,
        agent,
        count: better.length,
        list: listed(t, locale, better, context),
      }),
    );
  if (worse.length > 0)
    sentences.push(
      t(round.verdict === "criteria_worse" ? "criteria.worse" : "criteria.worseBeside", {
        number: round.number,
        agent,
        count: worse.length,
        list: listed(t, locale, worse, context),
      }),
    );
  if (skillWorse.length > 0)
    sentences.push(
      t("criteria.skillWorse", {
        agent,
        count: skillWorse.length,
        list: listed(t, locale, skillWorse, context),
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

function movedText(t: Translate, item: CriterionRow): string {
  if (item.fixed > 0 && item.broken > 0)
    return t("movedBoth", { fixed: item.fixed, broken: item.broken });
  if (item.fixed > 0) return t("movedFixed", { count: item.fixed });
  if (item.broken > 0) return t("movedBroken", { count: item.broken });
  return t("movedNone");
}

/** Every criterion a change was measured on: passed before and after, and what moved. */
export function CriteriaTable({ criteria }: { criteria: CriterionRow[] }) {
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
            <tr key={item.key} className="border-t">
              <td className="py-1 pr-3">
                {scoredName(item, criteria)}
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
