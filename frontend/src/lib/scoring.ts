import type { CaseCheck, DatasetStats } from "@/types/datasets";
import type { CaseScore, DatasetScoring, ScorerResult } from "@/types/scoring";

/** What a dataset is scored with before anybody configures it - the server's defaults. */
export const DEFAULT_SCORING: DatasetScoring = {
  checks: { enabled: true, required: true, defaults: [] },
  trajectory: { enabled: true, required: true },
  judge: {
    enabled: false,
    agent_id: null,
    model_profile_id: null,
    scale_max: 5,
    pass_at: 4,
    criteria: [],
  },
  reference: { enabled: false, required: true },
  review: { select: "none" },
};

/**
 * Why a configuration could score nothing, as a catalog key - the server refuses
 * the same two - or `null` when it can be saved.
 */
export function scoringProblem(scoring: DatasetScoring): string | null {
  const { checks, trajectory, judge, reference } = scoring;
  if (![checks, trajectory, judge, reference].some((scorer) => scorer.enabled)) {
    return "problem.noScorer";
  }
  if (judge.enabled && judge.criteria.length === 0) return "problem.noCriterion";
  return null;
}

/**
 * Whether scoring this case calls the eval judge, which is a paid run.
 *
 * The same rule the server applies: the rubric, the reference comparison where
 * the case has a reference answer, or a `judge` check - the case's own or a
 * default - while checks are on.
 */
export function callsJudge(
  scoring: DatasetScoring,
  kase: { reference_answer: string | null; checks: CaseCheck[] },
): boolean {
  if (scoring.judge.enabled && scoring.judge.criteria.length > 0) return true;
  if (scoring.reference.enabled && kase.reference_answer) return true;
  return (
    scoring.checks.enabled &&
    [...scoring.checks.defaults, ...kase.checks].some((check) => check.type === "judge")
  );
}

/**
 * Why a scorer did not give a verdict, as the catalog names it.
 *
 * Each code has its own key - "AI assistance is off" asks an admin for a switch,
 * "publish the judge" asks somebody to pick a model - and a code this build does
 * not know falls back to the server's own sentence.
 */
const REASON_KEYS = {
  ai_assistance_off: "reason.aiAssistanceOff",
  judge_unpublished: "reason.judgeUnpublished",
  judge_archived: "reason.judgeArchived",
  judge_no_access: "reason.judgeNoAccess",
  judge_no_model: "reason.judgeNoModel",
  judge_not_seeded: "reason.judgeNotSeeded",
  judge_missing: "reason.judgeMissing",
  judge_budget: "reason.judgeBudget",
  judge_run_failed: "reason.judgeRunFailed",
  judge_output_invalid: "reason.judgeOutputInvalid",
  judge_ungraded: "reason.judgeUngraded",
  judge_reason_echo: "reason.judgeReasonEcho",
  judge_counter_unsupported: "reason.judgeCounterUnsupported",
} as const;

export function reasonKey(result: ScorerResult): string | null {
  return reasonKeyOf(result.reason_code);
}

/** The catalog key for a reason code, or null for a code this build does not know. */
export function reasonKeyOf(code: string | null): string | null {
  if (code === null || !(code in REASON_KEYS)) return null;
  return REASON_KEYS[code as keyof typeof REASON_KEYS];
}

/** A check as one line: its type, then what it was given. Code the case holds, not copy. */
export function describeCheck({ type, ...given }: CaseCheck): string {
  const values = Object.values(given);
  if (values.length === 1 && typeof values[0] !== "object") return `${type} ${String(values[0])}`;
  return values.length === 0 ? type : `${type} ${JSON.stringify(given)}`;
}

/** Scores in a row that one eval run made of one agent, or that were graded by hand. */
export interface ScoreGroup {
  key: string;
  evalRunId: string | null;
  scores: CaseScore[];
}

/**
 * A page of scores cut where the eval run or the answering agent changes.
 *
 * The groups keep the server's order, newest first, so a group is a run of
 * neighbours; the same eval run split by another between them is shown twice
 * rather than reordered. Inside a group the scores read in the order they were
 * graded, which for an eval run is the order of the dataset's cases.
 */
export function groupScores(scores: CaseScore[]): ScoreGroup[] {
  const groups: ScoreGroup[] = [];
  for (const score of scores) {
    const key = `${score.eval_run_id ?? "hand"}:${score.agent_id ?? "gone"}`;
    const last = groups.at(-1);
    if (last?.key === key) last.scores.push(score);
    else groups.push({ key, evalRunId: score.eval_run_id, scores: [score] });
  }
  for (const group of groups) {
    group.scores.sort((a, b) => a.created_at.localeCompare(b.created_at));
  }
  return groups;
}

/**
 * How many of a dataset's cases a configuration would grade nothing on.
 *
 * A case is graded when the judge has criteria - it reads every case - or when a
 * scorer that is on finds what it reads on the case: checks (the case's own, or
 * a default every case gets), expected tool calls, a reference answer.
 */
export function ungradedCases(
  scoring: DatasetScoring,
  stats: DatasetStats,
  defaultChecks: number,
): number {
  const { checks, trajectory, judge, reference } = scoring;
  if (judge.enabled && judge.criteria.length > 0) return 0;
  return stats.expectation_mix
    .filter(
      (mix) =>
        !(checks.enabled && (mix.checks || defaultChecks > 0)) &&
        !(trajectory.enabled && mix.tool_calls) &&
        !(reference.enabled && mix.reference),
    )
    .reduce((total, mix) => total + mix.cases, 0);
}

/** A judge criterion's text is at most this long, as the server holds it. */
export const MAX_CRITERION = 1000;

/**
 * A name for a criterion made from its text: its first words, kept short, and
 * numbered when the rubric already holds the name.
 */
export function criterionNameFrom(text: string, taken: string[]): string {
  const words = text.trim().split(/\s+/).slice(0, 6).join(" ").slice(0, 60);
  let name = words;
  for (let count = 2; taken.includes(name); count += 1) name = `${words} ${count}`;
  return name;
}
