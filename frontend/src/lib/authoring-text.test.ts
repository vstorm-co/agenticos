import { describe, expect, it } from "vitest";
import { batch, hunk } from "@/test-utils/authoring";
import { expectedEffect } from "./authoring-text";

describe("expectedEffect", () => {
  it("never shows an effect for an empty batch", () => {
    expect(expectedEffect(batch({ hunks: [] }), String)).toBe("");
  });
  it("replaces raw model identities with a distinct source count", () => {
    const source = "467abd40-2539-49d3-b239-2c960f7b7b07";
    const result = expectedEffect(
      batch({
        expected_effect: `Prevent bad runs like ${source}`,
        hunks: [
          hunk({
            evidence: [
              { run_id: source, quote: "bad" },
              { run_id: source, quote: "wrong" },
            ],
          }),
        ],
      }),
      (count) => `Proposed for ${count} source answers`,
    );
    expect(result).toBe("Proposed for 1 source answers");
    expect(result).not.toContain(source);
  });
  it("preserves an ordinary expected outcome", () => {
    expect(expectedEffect(batch(), String)).toBe("Refund answers name 30 days");
  });
});
