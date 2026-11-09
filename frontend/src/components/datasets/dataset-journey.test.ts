import { describe, expect, it } from "vitest";
import { DEFAULT_SCORING } from "@/lib/scoring";
import { datasetFixture } from "@/test-utils/datasets";
import { datasetNextStep } from "./dataset-journey";

describe("dataset readiness", () => {
  it("requires actual grading coverage before declaring the dataset ready", () => {
    expect(datasetNextStep(datasetFixture({ case_count: 0 }))).toBe("cases");
    expect(datasetNextStep(datasetFixture())).toBe("grading");
    expect(
      datasetNextStep(
        datasetFixture({
          scoring: { ...DEFAULT_SCORING, reference: { enabled: true, required: true } },
        }),
      ),
    ).toBe("evals");
    expect(
      datasetNextStep(
        datasetFixture({
          scoring: { ...DEFAULT_SCORING, judge: { ...DEFAULT_SCORING.judge, enabled: true } },
        }),
      ),
    ).toBe("grading");
  });
});
