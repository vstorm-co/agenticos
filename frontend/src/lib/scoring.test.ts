import { describe, expect, it } from "vitest";

import { reasonKey } from "./scoring";
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
