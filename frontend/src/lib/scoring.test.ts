import { describe, expect, it } from "vitest";

import { DEFAULT_SCORING, callsJudge, reasonKey, scoringProblem } from "./scoring";
import type { ScorerResult } from "@/types/scoring";

function result(reason_code: string | null): ScorerResult {
  return {
    scorer: "judge",
    name: "tone",
    required: true,
    status: "skipped",
    score: null,
    reason: "from the server",
    reason_code,
    judge_run_id: null,
  };
}

describe("reasonKey", () => {
  it("names each cause the judge did not run for on its own", () => {
    expect(reasonKey(result("ai_assistance_off"))).toBe("reason.aiAssistanceOff");
    expect(reasonKey(result("judge_budget"))).toBe("reason.judgeBudget");
    expect(reasonKey(result("judge_no_model"))).toBe("reason.judgeNoModel");
  });

  it("leaves a code this build does not know, and no code, to the server's sentence", () => {
    expect(reasonKey(result("judge_output_invalid"))).toBeNull();
    expect(reasonKey(result(null))).toBeNull();
  });
});

describe("scoringProblem", () => {
  const off = { ...DEFAULT_SCORING.checks, enabled: false };

  it("refuses a configuration with every scorer off", () => {
    expect(
      scoringProblem({
        ...DEFAULT_SCORING,
        checks: off,
        trajectory: { enabled: false, required: true },
      }),
    ).toBe("problem.noScorer");
  });

  it("refuses a judge with nothing to grade, and accepts the defaults", () => {
    const judge = { ...DEFAULT_SCORING.judge, enabled: true };
    expect(scoringProblem({ ...DEFAULT_SCORING, judge })).toBe("problem.noCriterion");
    expect(scoringProblem(DEFAULT_SCORING)).toBeNull();
  });
});

describe("callsJudge", () => {
  const plain = { reference_answer: null, checks: [] };

  it("calls the judge for a rubric, a reference the case has, or a judge check", () => {
    const rubric = {
      ...DEFAULT_SCORING,
      judge: {
        ...DEFAULT_SCORING.judge,
        enabled: true,
        criteria: [{ name: "tone", description: "Polite", required: true }],
      },
    };
    const reference = { ...DEFAULT_SCORING, reference: { enabled: true, required: true } };
    const defaults = {
      ...DEFAULT_SCORING,
      checks: { ...DEFAULT_SCORING.checks, defaults: [{ type: "judge", criterion: "Polite" }] },
    };

    expect(callsJudge(rubric, plain)).toBe(true);
    expect(callsJudge(reference, { ...plain, reference_answer: "Thirty days." })).toBe(true);
    expect(callsJudge(DEFAULT_SCORING, { ...plain, checks: [{ type: "judge" }] })).toBe(true);
    expect(callsJudge(defaults, plain)).toBe(true);
  });

  it("does not for rule-based scoring, a reference the case lacks, or checks switched off", () => {
    const reference = { ...DEFAULT_SCORING, reference: { enabled: true, required: true } };
    const checksOff = { ...DEFAULT_SCORING, checks: { ...DEFAULT_SCORING.checks, enabled: false } };

    expect(callsJudge(DEFAULT_SCORING, plain)).toBe(false);
    expect(callsJudge(reference, plain)).toBe(false);
    expect(callsJudge(checksOff, { ...plain, checks: [{ type: "judge" }] })).toBe(false);
  });
});
