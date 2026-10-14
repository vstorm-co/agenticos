import { describe, expect, it } from "vitest";

import { DEFAULT_SCORING, reasonKey, scoringProblem } from "./scoring";
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
