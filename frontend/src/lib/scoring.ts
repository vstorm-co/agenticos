import type { CaseCheck } from "@/types/datasets";
import type { DatasetScoring, ScorerResult } from "@/types/scoring";

/** What a dataset is scored with before anybody configures it - the server's defaults. */
export const DEFAULT_SCORING: DatasetScoring = {
  checks: { enabled: true, required: true, defaults: [] },
  trajectory: { enabled: true, required: true },
  judge: { enabled: false, model_profile_id: null, scale_max: 5, pass_at: 4, criteria: [] },
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
  judge_budget: "reason.judgeBudget",
} as const;

export function reasonKey(result: ScorerResult): string | null {
  const code = result.reason_code;
  if (code === null || !(code in REASON_KEYS)) return null;
  return REASON_KEYS[code as keyof typeof REASON_KEYS];
}
